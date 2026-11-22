"""JUnit XML exporter for native CI/CD test runners."""

from __future__ import annotations

from pathlib import Path
from typing import IO, Any
import xml.etree.ElementTree as ET
from xml.dom import minidom


class JUnitExporter:
    """Export session validation checks, replay assertions, and errors to standard JUnit XML."""

    def __init__(self, pretty: bool = True) -> None:
        self.pretty = pretty

    def generate_junit(
        self,
        session: dict[str, Any] | None = None,
        validation_results: list[Any] | None = None,
        replay_mismatches: list[dict[str, Any]] | None = None,
        errors: list[dict[str, Any]] | None = None,
        warnings: list[str] | None = None,
    ) -> str:
        """Generate a valid JUnit XML string representation."""
        session_id = session.get("id", 0) if session else 0

        testsuites = ET.Element("testsuites", attrib={"name": "mcp-debugger"})

        total_tests = 0
        total_failures = 0
        total_errors = 0
        total_time = 0.0

        suite = ET.SubElement(
            testsuites,
            "testsuite",
            attrib={"name": f"session-{session_id}" if session_id else "global"},
        )

        suite_tests = 0
        suite_failures = 0
        suite_errors = 0

        # 1. Validation results
        if validation_results:
            for v in validation_results:
                suite_tests += 1
                rule_name = getattr(v, "rule_name", "UNKNOWN")
                passed = getattr(v, "passed", True)
                message = getattr(v, "message", "")
                severity = getattr(v, "severity", "critical")

                case = ET.SubElement(
                    suite,
                    "testcase",
                    attrib={
                        "classname": "protocol.validation",
                        "name": rule_name,
                        "time": "0.0",
                    },
                )
                if not passed:
                    suite_failures += 1
                    failure_type = "ProtocolViolation" if severity == "critical" else "ProtocolWarning"
                    fail_elem = ET.SubElement(
                        case,
                        "failure",
                        attrib={
                            "message": message or f"Violation of rule {rule_name}",
                            "type": failure_type,
                        },
                    )
                    fail_elem.text = message

        # 2. Replay checks
        if replay_mismatches:
            for r in replay_mismatches:
                suite_tests += 1
                msg_id = r.get("original_message_id", 0)
                mismatches = r.get("mismatches", 0)
                err_msg = r.get("error", "Replay output divergence mismatch")

                case = ET.SubElement(
                    suite,
                    "testcase",
                    attrib={
                        "classname": "replay.verification",
                        "name": f"replay-msg-{msg_id}",
                        "time": "0.0",
                    },
                )
                if mismatches > 0 or r.get("status") == "mismatch":
                    suite_failures += 1
                    fail_elem = ET.SubElement(
                        case,
                        "failure",
                        attrib={
                            "message": err_msg,
                            "type": "ReplayRegression",
                        },
                    )
                    fail_elem.text = err_msg

        # 3. Session errors
        if errors:
            for err in errors:
                suite_tests += 1
                suite_errors += 1
                etype = err.get("error_type", "SessionError")
                emsg = err.get("message", "Unspecified error")

                case = ET.SubElement(
                    suite,
                    "testcase",
                    attrib={
                        "classname": "session.execution",
                        "name": f"error-{err.get('id', suite_tests)}",
                        "time": "0.0",
                    },
                )
                err_elem = ET.SubElement(
                    case,
                    "error",
                    attrib={
                        "message": emsg,
                        "type": etype,
                    },
                )
                err_elem.text = emsg

        # 4. Warnings in system-out
        if warnings:
            sys_out = ET.SubElement(suite, "system-out")
            sys_out.text = "\n".join(warnings)

        suite.attrib["tests"] = str(suite_tests)
        suite.attrib["failures"] = str(suite_failures)
        suite.attrib["errors"] = str(suite_errors)
        suite.attrib["time"] = f"{total_time:.3f}"

        total_tests += suite_tests
        total_failures += suite_failures
        total_errors += suite_errors

        testsuites.attrib["tests"] = str(total_tests)
        testsuites.attrib["failures"] = str(total_failures)
        testsuites.attrib["errors"] = str(total_errors)
        testsuites.attrib["time"] = f"{total_time:.3f}"

        raw_xml = ET.tostring(testsuites, encoding="utf-8")
        if self.pretty:
            parsed = minidom.parseString(raw_xml)
            return parsed.toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")
        return f'<?xml version="1.0" encoding="utf-8"?>\n{raw_xml.decode("utf-8")}'

    def export(
        self,
        out: str | Path | IO[str],
        session: dict[str, Any] | None = None,
        validation_results: list[Any] | None = None,
        replay_mismatches: list[dict[str, Any]] | None = None,
        errors: list[dict[str, Any]] | None = None,
        warnings: list[str] | None = None,
    ) -> None:
        """Write the generated JUnit XML to a file path or file-like object."""
        content = self.generate_junit(
            session=session,
            validation_results=validation_results,
            replay_mismatches=replay_mismatches,
            errors=errors,
            warnings=warnings,
        )
        if isinstance(out, (str, Path)):
            p = Path(out)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        else:
            out.write(content)
