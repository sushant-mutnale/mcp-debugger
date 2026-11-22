"""Unit tests for JUnit XML exporter."""

from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET

from typer.testing import CliRunner

from mcp_debugger.cli import app
from mcp_debugger.exporters.junit_exporter import JUnitExporter
from mcp_debugger.protocol.validator import ValidationResult
from mcp_debugger.storage.database import Database


def test_junit_empty_run() -> None:
    """Empty run produces valid XML testsuites document with zero tests."""
    exporter = JUnitExporter()
    xml_str = exporter.generate_junit()

    root = ET.fromstring(xml_str)
    assert root.tag == "testsuites"
    assert root.attrib.get("tests") == "0"
    assert root.attrib.get("failures") == "0"
    assert root.attrib.get("errors") == "0"


def test_junit_with_validation_results() -> None:
    """Validation checks map to passed and failed JUnit testcases."""
    exporter = JUnitExporter()

    v_pass = ValidationResult(
        rule_name="JSONRPC_ID_TYPE",
        passed=True,
        severity="info",
        message="Valid JSONRPC id",
    )
    v_fail = ValidationResult(
        rule_name="TOOL_TIMEOUT",
        passed=False,
        severity="critical",
        message="Tool execution exceeded timeout of 30s",
    )

    xml_str = exporter.generate_junit(
        session={"id": 42, "name": "test-session"},
        validation_results=[v_pass, v_fail],
    )

    root = ET.fromstring(xml_str)
    assert root.tag == "testsuites"
    assert root.attrib.get("tests") == "2"
    assert root.attrib.get("failures") == "1"
    assert root.attrib.get("errors") == "0"

    suite = root.find("testsuite")
    assert suite is not None
    assert suite.attrib.get("name") == "session-42"
    assert suite.attrib.get("tests") == "2"
    assert suite.attrib.get("failures") == "1"

    cases = suite.findall("testcase")
    assert len(cases) == 2

    # Check passed case
    case_pass = next(c for c in cases if c.attrib.get("name") == "JSONRPC_ID_TYPE")
    assert case_pass.attrib.get("classname") == "protocol.validation"
    assert case_pass.find("failure") is None

    # Check failed case
    case_fail = next(c for c in cases if c.attrib.get("name") == "TOOL_TIMEOUT")
    assert case_fail.attrib.get("classname") == "protocol.validation"
    fail_elem = case_fail.find("failure")
    assert fail_elem is not None
    assert "Tool execution exceeded timeout" in fail_elem.attrib.get("message", "")
    assert fail_elem.attrib.get("type") == "ProtocolViolation"


def test_junit_with_replay_mismatches() -> None:
    """Replay regressions map to failed testcases under replay class."""
    exporter = JUnitExporter()

    replays = [
        {
            "id": 1,
            "session_id": 42,
            "original_message_id": 105,
            "status": "mismatch",
            "mismatches": 2,
            "error": "Field 'result.data' diverged from cassette output",
        }
    ]

    xml_str = exporter.generate_junit(
        session={"id": 42},
        replay_mismatches=replays,
    )

    root = ET.fromstring(xml_str)
    assert root.attrib.get("tests") == "1"
    assert root.attrib.get("failures") == "1"

    suite = root.find("testsuite")
    assert suite is not None
    case = suite.find("testcase")
    assert case is not None
    assert case.attrib.get("classname") == "replay.verification"
    assert case.attrib.get("name") == "replay-msg-105"

    failure = case.find("failure")
    assert failure is not None
    assert failure.attrib.get("type") == "ReplayRegression"
    assert "diverged" in failure.attrib.get("message", "")


def test_junit_with_session_errors() -> None:
    """Session errors map to error testcases."""
    exporter = JUnitExporter()

    errors = [
        {
            "id": 1,
            "error_type": "ConnectionRefused",
            "message": "Failed to connect to MCP daemon on port 8000",
        }
    ]

    xml_str = exporter.generate_junit(
        session={"id": 42},
        errors=errors,
    )

    root = ET.fromstring(xml_str)
    assert root.attrib.get("tests") == "1"
    assert root.attrib.get("errors") == "1"

    suite = root.find("testsuite")
    assert suite is not None
    case = suite.find("testcase")
    assert case is not None
    assert case.attrib.get("classname") == "session.execution"

    error_elem = case.find("error")
    assert error_elem is not None
    assert error_elem.attrib.get("type") == "ConnectionRefused"
    assert "Failed to connect" in error_elem.attrib.get("message", "")


def test_junit_file_export(tmp_path: Path) -> None:
    """export() writes valid XML to a file or stream."""
    exporter = JUnitExporter()
    out_file = tmp_path / "junit_report.xml"

    v_pass = ValidationResult(
        rule_name="SCHEMA_VALID",
        passed=True,
        severity="info",
        message="Pass",
    )

    exporter.export(
        out=out_file,
        session={"id": 10},
        validation_results=[v_pass],
    )

    assert out_file.exists()
    content = out_file.read_text(encoding="utf-8")
    assert "<?xml" in content
    root = ET.fromstring(content)
    assert root.tag == "testsuites"
    assert root.attrib.get("tests") == "1"


def test_cli_ci_junit_flag(mock_db_path: str, tmp_path: Path, runner: CliRunner) -> None:
    """The ci command accepts --junit <path> and writes test report XML."""
    import asyncio

    async def _setup() -> int:
        db = Database(mock_db_path)
        await db.connect()
        try:
            sid = await db.create_session("ci-junit-target")
            await db.log_message(
                session_id=sid,
                direction="client_to_server",
                message={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            )
            return sid
        finally:
            await db.close()

    session_id = asyncio.run(_setup())

    junit_out = tmp_path / "ci_results.xml"
    result = runner.invoke(
        app,
        ["ci", str(session_id), "--junit", str(junit_out)],
    )
    assert junit_out.exists(), result.output
    content = junit_out.read_text(encoding="utf-8")
    assert "<?xml" in content
    root = ET.fromstring(content)
    assert root.tag == "testsuites"


def test_cli_export_junit_flag(mock_db_path: str, tmp_path: Path, runner: CliRunner) -> None:
    """The export command accepts --format junit or --junit <path>."""
    import asyncio

    async def _setup() -> int:
        db = Database(mock_db_path)
        await db.connect()
        try:
            sid = await db.create_session("export-junit-target")
            await db.log_message(
                session_id=sid,
                direction="client_to_server",
                message={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            )
            return sid
        finally:
            await db.close()

    session_id = asyncio.run(_setup())

    # 1. via --format junit to stdout
    result = runner.invoke(
        app,
        ["export", str(session_id), "--format", "junit"],
    )
    assert result.exit_code == 0, result.output
    assert "<testsuites" in result.stdout

    # 2. via --junit file
    junit_file = tmp_path / "exported.xml"
    result2 = runner.invoke(
        app,
        ["export", str(session_id), "--junit", str(junit_file)],
    )
    assert result2.exit_code == 0, result2.output
    assert junit_file.exists()
    assert "<testsuites" in junit_file.read_text(encoding="utf-8")
