"""SARIF v2.1.0 exporter for GitHub Code Scanning and CI/CD quality gates."""

from __future__ import annotations

import json
from pathlib import Path
from typing import IO, Any

from mcp_debugger.version import __version__


class SarifExporter:
    """Export validation, causal attribution, and replay regressions into SARIF v2.1.0."""

    def __init__(self, pretty: bool = True) -> None:
        self.pretty = pretty

    def generate_sarif(
        self,
        session: dict[str, Any] | None = None,
        validation_results: list[Any] | None = None,
        attribution_report: Any | None = None,
        replay_mismatches: list[dict[str, Any]] | None = None,
        warnings: list[str] | None = None,
    ) -> dict[str, Any]:
        """Generate a SARIF v2.1.0 JSON-compatible dictionary."""
        session_id = session.get("id", 0) if session else 0

        rules_dict: dict[str, dict[str, Any]] = {
            "MCP-CAUSAL-POC": {
                "id": "MCP-CAUSAL-POC",
                "name": "PointOfCommitment",
                "shortDescription": {
                    "text": "Causal failure point of commitment identified by step ablation",
                },
                "defaultConfiguration": {"level": "error"},
            },
            "MCP-REGRESSION": {
                "id": "MCP-REGRESSION",
                "name": "ReplayRegression",
                "shortDescription": {
                    "text": "Replay output divergence mismatch detected",
                },
                "defaultConfiguration": {"level": "error"},
            },
            "MCP-WARN": {
                "id": "MCP-WARN",
                "name": "GeneralWarning",
                "shortDescription": {
                    "text": "Performance or budget threshold warning",
                },
                "defaultConfiguration": {"level": "warning"},
            },
        }

        results: list[dict[str, Any]] = []

        # 1. Validation results
        if validation_results:
            for v in validation_results:
                if not getattr(v, "passed", True):
                    rule_name = getattr(v, "rule_name", "UNKNOWN")
                    rule_id = f"MCP-PROTO-{rule_name}"
                    severity = getattr(v, "severity", "critical")
                    level = "error" if severity == "critical" else "warning"

                    if rule_id not in rules_dict:
                        rules_dict[rule_id] = {
                            "id": rule_id,
                            "name": f"Protocol_{rule_name}",
                            "shortDescription": {"text": f"Protocol rule violation: {rule_name}"},
                            "defaultConfiguration": {"level": level},
                        }

                    results.append({
                        "ruleId": rule_id,
                        "level": level,
                        "message": {"text": getattr(v, "message", "Protocol validation failure")},
                        "locations": [
                            {
                                "physicalLocation": {
                                    "artifactLocation": {
                                        "uri": f"session://{session_id}/protocol/{rule_name}",
                                    },
                                    "region": {"startLine": 1},
                                },
                            }
                        ],
                    })

        # 2. Causal attribution point of commitment
        if attribution_report:
            poc = getattr(attribution_report, "point_of_commitment", None)
            if poc is not None:
                step_idx = getattr(poc, "step_index", 0)
                tool_name = getattr(poc, "tool_name", "unknown")
                desc = getattr(poc, "description", "")
                ptype = getattr(poc, "perturbation", None)
                ptype_str = ptype.value if hasattr(ptype, "value") else str(ptype)

                results.append({
                    "ruleId": "MCP-CAUSAL-POC",
                    "level": "error",
                    "message": {
                        "text": (
                            f"Point of Commitment isolated at Step #{step_idx} ({tool_name}). "
                            f"{desc} (Perturbation: {ptype_str})."
                        ),
                    },
                    "locations": [
                        {
                            "physicalLocation": {
                                "artifactLocation": {
                                    "uri": f"session://{session_id}/step/{step_idx}",
                                },
                                "region": {"startLine": step_idx + 1},
                            },
                        }
                    ],
                })

        # 3. Replay regressions
        if replay_mismatches:
            for mismatch in replay_mismatches:
                msg_id = mismatch.get("original_message_id", 0)
                err_msg = mismatch.get("error") or "Output divergence mismatch"
                results.append({
                    "ruleId": "MCP-REGRESSION",
                    "level": "error",
                    "message": {"text": f"Replay divergence mismatch: {err_msg}"},
                    "locations": [
                        {
                            "physicalLocation": {
                                "artifactLocation": {
                                    "uri": f"session://{session_id}/message/{msg_id}",
                                },
                                "region": {"startLine": 1},
                            },
                        }
                    ],
                })

        # 4. Warnings (latency, cost, etc.)
        if warnings:
            for w in warnings:
                results.append({
                    "ruleId": "MCP-WARN",
                    "level": "warning",
                    "message": {"text": w},
                    "locations": [
                        {
                            "physicalLocation": {
                                "artifactLocation": {
                                    "uri": f"session://{session_id}",
                                },
                                "region": {"startLine": 1},
                            },
                        }
                    ],
                })

        return {
            "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
            "version": "2.1.0",
            "runs": [
                {
                    "tool": {
                        "driver": {
                            "name": "mcp-debugger",
                            "version": __version__,
                            "informationUri": "https://github.com/sushant-mutnale/mcp-debugger",
                            "rules": list(rules_dict.values()),
                        },
                    },
                    "results": results,
                }
            ],
        }

    def export(
        self,
        out: IO[str] | Path | str,
        session: dict[str, Any] | None = None,
        validation_results: list[Any] | None = None,
        attribution_report: Any | None = None,
        replay_mismatches: list[dict[str, Any]] | None = None,
        warnings: list[str] | None = None,
    ) -> None:
        """Export session findings into a SARIF file or stream."""
        data = self.generate_sarif(
            session=session,
            validation_results=validation_results,
            attribution_report=attribution_report,
            replay_mismatches=replay_mismatches,
            warnings=warnings,
        )
        indent = 2 if self.pretty else None
        serialized = json.dumps(data, indent=indent)

        if isinstance(out, (str, Path)):
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            Path(out).write_text(serialized, encoding="utf-8")
        else:
            out.write(serialized)
