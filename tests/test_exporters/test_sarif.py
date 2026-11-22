"""Unit tests for SARIF v2.1.0 exporter."""

import asyncio
import json
from pathlib import Path
from typer.testing import CliRunner

from mcp_debugger.cli import app
from mcp_debugger.exporters.sarif_exporter import SarifExporter
from mcp_debugger.protocol.validator import ValidationResult
from mcp_debugger.attribution.models import PointOfCommitment, PerturbationType, AttributionReport, FailureCategory, FailureDiagnosis
from mcp_debugger.storage.database import Database


def test_sarif_empty_run() -> None:
    """SARIF output contains schema, driver definition, and empty results on clean run."""
    exporter = SarifExporter()
    sarif = exporter.generate_sarif()

    assert sarif["version"] == "2.1.0"
    assert "$schema" in sarif
    assert len(sarif["runs"]) == 1

    driver = sarif["runs"][0]["tool"]["driver"]
    assert driver["name"] == "mcp-debugger"
    assert len(sarif["runs"][0]["results"]) == 0


def test_sarif_with_validation_results() -> None:
    """Protocol violations generate appropriate SARIF error and warning results."""
    exporter = SarifExporter()

    v_crit = ValidationResult(
        rule_name="JSONRPC_INIT_FIRST",
        passed=False,
        severity="critical",
        message="Client must initialize before sending tool calls",
    )
    v_warn = ValidationResult(
        rule_name="OPTIONAL_CAPABILITIES",
        passed=False,
        severity="warning",
        message="Server omitted optional experimental capabilities",
    )

    sarif = exporter.generate_sarif(
        session={"id": 42},
        validation_results=[v_crit, v_warn],
    )

    results = sarif["runs"][0]["results"]
    assert len(results) == 2

    # Critical -> error
    assert results[0]["ruleId"] == "MCP-PROTO-JSONRPC_INIT_FIRST"
    assert results[0]["level"] == "error"
    assert "initialize" in results[0]["message"]["text"]
    assert "session://42" in results[0]["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]

    # Warning -> warning
    assert results[1]["ruleId"] == "MCP-PROTO-OPTIONAL_CAPABILITIES"
    assert results[1]["level"] == "warning"


def test_sarif_with_attribution_poc() -> None:
    """Causal attribution Point-of-Commitment generates MCP-CAUSAL-POC result."""
    exporter = SarifExporter()

    poc = PointOfCommitment(
        step_index=3,
        step_type="tool_call",
        tool_name="read_file",
        perturbation=PerturbationType.EMPTY_RESULT,
        description="Marginal divergence 0.85 when perturbed with empty result",
    )

    diagnosis = FailureDiagnosis(
        session_id=10,
        category=FailureCategory.AGENT,
        root_cause_step_index=3,
        summary="Agent unhandled empty response",
        recommendations=["Empty list returned"],
    )

    report = AttributionReport(
        session_id=10,
        original_diagnosis=diagnosis,
        point_of_commitment=poc,
    )

    sarif = exporter.generate_sarif(
        session={"id": 10},
        attribution_report=report,
    )

    results = sarif["runs"][0]["results"]
    assert len(results) == 1
    assert results[0]["ruleId"] == "MCP-CAUSAL-POC"
    assert results[0]["level"] == "error"
    assert "Step #3 (read_file)" in results[0]["message"]["text"]
    assert "0.85" in results[0]["message"]["text"]


def test_sarif_with_replay_mismatches() -> None:
    """Replay regression mismatches generate MCP-REGRESSION results."""
    exporter = SarifExporter()

    mismatches = [
        {
            "original_message_id": 12,
            "error": "Output mismatch on property 'temperature'",
        }
    ]

    sarif = exporter.generate_sarif(
        session={"id": 7},
        replay_mismatches=mismatches,
    )

    results = sarif["runs"][0]["results"]
    assert len(results) == 1
    assert results[0]["ruleId"] == "MCP-REGRESSION"
    assert results[0]["level"] == "error"
    assert "temperature" in results[0]["message"]["text"]


def test_sarif_file_export(tmp_path: Path) -> None:
    """Exporter writes valid JSON file to target path."""
    exporter = SarifExporter(pretty=True)
    out_file = tmp_path / "results.sarif"

    exporter.export(
        out=str(out_file),
        session={"id": 99},
        warnings=["High token spend alert"],
    )

    assert out_file.exists()
    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert data["version"] == "2.1.0"
    assert len(data["runs"][0]["results"]) == 1
    assert data["runs"][0]["results"][0]["level"] == "warning"


def test_cli_ci_sarif_flag(mock_db_path: str, runner: CliRunner, tmp_path: Path) -> None:
    """mcp-debugger ci generates SARIF report when --sarif flag is supplied."""

    async def setup_bad() -> int:
        db = Database(db_path=mock_db_path)
        await db.connect()
        sid = await db.create_session("sarif-ci-session")

        await db.log_message(
            sid,
            "client_to_server",
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
            },
        )
        await db.close()
        return sid

    sid = asyncio.run(setup_bad())
    sarif_path = tmp_path / "ci_report.sarif"

    result = runner.invoke(app, ["ci", str(sid), "--sarif", str(sarif_path)])
    assert result.exit_code == 1
    assert sarif_path.exists()

    sarif_data = json.loads(sarif_path.read_text(encoding="utf-8"))
    assert sarif_data["version"] == "2.1.0"
    assert len(sarif_data["runs"][0]["results"]) >= 1
