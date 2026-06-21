"""Edge case and error handling tests for mcp-debugger CLI subcommands."""

import json
import os
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

from typer.testing import CliRunner

from mcp_debugger.cli import app, calculate_compliance_score
from mcp_debugger.protocol.validator import ValidationResult


# ===========================================================================
# 1. PROXY COMMAND EDGE CASES
# ===========================================================================

def test_proxy_database_session_failure(runner: CliRunner) -> None:
    """Verify that proxy exits with code 1 if create_session fails (returns -1)."""
    with patch("mcp_debugger.storage.database.Database.connect", new_callable=AsyncMock):
        with patch("mcp_debugger.storage.database.Database.create_session", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = -1
            result = runner.invoke(app, ["proxy", "--server", "dummy-server"])
            assert result.exit_code == 1
            assert "Failed to create database session" in result.stdout or "Failed to create database session" in result.stderr


def test_proxy_keyboard_interrupt(runner: CliRunner) -> None:
    """Verify that proxy exits cleanly with code 0 on KeyboardInterrupt."""
    with patch("asyncio.run", side_effect=KeyboardInterrupt):
        result = runner.invoke(app, ["proxy", "--server", "dummy-server"])
        assert result.exit_code == 0


# ===========================================================================
# 2. LIST COMMAND EDGE CASES
# ===========================================================================

def test_list_database_error(runner: CliRunner) -> None:
    """Verify that list exits with code 1 and suggestion on DatabaseError."""
    with patch("mcp_debugger.storage.database.Database.connect", new_callable=AsyncMock):
        with patch("mcp_debugger.storage.database.Database.get_sessions", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = sqlite3.DatabaseError("Corrupt DB")
            result = runner.invoke(app, ["list"])
            assert result.exit_code == 1
            assert "corrupted or invalid" in result.stdout


def test_list_general_exception(runner: CliRunner) -> None:
    """Verify that list exits with code 1 on generic connect Exception."""
    with patch("mcp_debugger.storage.database.Database.connect", new_callable=AsyncMock) as mock_connect:
        mock_connect.side_effect = Exception("Connect error")
        result = runner.invoke(app, ["list"])
        assert result.exit_code == 1
        assert "Error listing sessions" in result.stdout


# ===========================================================================
# 3. INSPECT COMMAND EDGE CASES
# ===========================================================================

def test_inspect_database_error(runner: CliRunner) -> None:
    """Verify that inspect handles database errors gracefully."""
    with patch("mcp_debugger.storage.database.Database.connect", new_callable=AsyncMock):
        with patch("mcp_debugger.storage.database.Database.get_session", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = sqlite3.DatabaseError("Corrupt DB")
            result = runner.invoke(app, ["inspect", "1"])
            assert result.exit_code == 1
            assert "corrupted or invalid" in result.stdout


def test_inspect_general_exception(runner: CliRunner) -> None:
    """Verify that inspect handles database connect exceptions."""
    with patch("mcp_debugger.storage.database.Database.connect", new_callable=AsyncMock) as mock_connect:
        mock_connect.side_effect = Exception("Connect error")
        result = runner.invoke(app, ["inspect", "1"])
        assert result.exit_code == 1
        assert "Error connecting to database" in result.stdout


def test_inspect_session_not_found(runner: CliRunner) -> None:
    """Verify that inspect exits with code 1 if session is missing."""
    with patch("mcp_debugger.storage.database.Database.connect", new_callable=AsyncMock):
        with patch("mcp_debugger.storage.database.Database.get_session", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = None
            result = runner.invoke(app, ["inspect", "999"])
            assert result.exit_code == 1
            assert "Session 999 not found" in result.stdout


def test_inspect_fetch_messages_failure(runner: CliRunner) -> None:
    """Verify that inspect handles message query failure gracefully."""
    with patch("mcp_debugger.storage.database.Database.connect", new_callable=AsyncMock):
        with patch("mcp_debugger.storage.database.Database.get_session", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {"id": 1}
            with patch("mcp_debugger.storage.database.Database.get_messages", new_callable=AsyncMock) as mock_msgs:
                mock_msgs.side_effect = Exception("Fetch error")
                result = runner.invoke(app, ["inspect", "1"])
                assert result.exit_code == 1
                assert "Error fetching messages" in result.stdout


def test_inspect_empty_messages(runner: CliRunner, tmp_path: Path) -> None:
    """Verify inspect output formatting when no messages are found."""
    with patch("mcp_debugger.storage.database.Database.connect", new_callable=AsyncMock):
        with patch("mcp_debugger.storage.database.Database.get_session", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {"id": 1}
            with patch("mcp_debugger.storage.database.Database.get_messages", new_callable=AsyncMock) as mock_msgs:
                mock_msgs.return_value = []
                with patch("mcp_debugger.storage.database.Database.get_errors", new_callable=AsyncMock) as mock_errs:
                    mock_errs.return_value = []

                    # Test output file with json mode
                    out_json = tmp_path / "empty.json"
                    result = runner.invoke(app, ["inspect", "1", "--json", "--output", str(out_json)])
                    assert result.exit_code == 0
                    assert out_json.read_text(encoding="utf-8") == "[]\n"

                    # Test stdout with json mode
                    result_stdout_json = runner.invoke(app, ["inspect", "1", "--json"])
                    assert result_stdout_json.exit_code == 0
                    assert result_stdout_json.stdout.strip() == "[]"

                    # Test output file with rich mode
                    out_rich = tmp_path / "empty.txt"
                    result_rich = runner.invoke(app, ["inspect", "1", "--output", str(out_rich)])
                    assert result_rich.exit_code == 0
                    assert out_rich.read_text(encoding="utf-8") == "No messages\n"


def test_inspect_json_modes_and_failures(runner: CliRunner, tmp_path: Path) -> None:
    """Verify inspect command JSON parser fallbacks and output redirects."""
    mock_messages = [
        {
            "id": 1,
            "message_id": "non-int-id",
            "message_type": "request",
            "direction": "client_to_server",
            "method": "tools/list",
            "params": "{invalid-json}",
            "result": "{invalid-json}",
            "error": "{invalid-json}",
            "timestamp": 1600000000000,
            "latency_ms": 10.0,
        }
    ]

    with patch("mcp_debugger.storage.database.Database.connect", new_callable=AsyncMock):
        with patch("mcp_debugger.storage.database.Database.get_session", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {"id": 1}
            with patch("mcp_debugger.storage.database.Database.get_messages", new_callable=AsyncMock, return_value=mock_messages):
                with patch("mcp_debugger.storage.database.Database.get_errors", new_callable=AsyncMock) as mock_errs:
                    mock_errs.side_effect = Exception("Get errors failed")  # triggers fallback error_map = {}

                    # Test with output file redirection
                    out_file = tmp_path / "messages.json"
                    result = runner.invoke(app, ["inspect", "1", "--json", "--output", str(out_file)])
                    assert result.exit_code == 0
                    data = json.loads(out_file.read_text(encoding="utf-8"))
                    assert len(data) == 1
                    # Verify fallback values passed as strings instead of dicts
                    assert data[0]["params"] == "{invalid-json}"
                    assert data[0]["result"] == "{invalid-json}"
                    assert data[0]["error"] == "{invalid-json}"


def test_inspect_rich_rendering_and_fallbacks(runner: CliRunner) -> None:
    """Verify fallback mechanisms for timestamp and parser errors in Rich inspection."""
    mock_messages = [
        {
            "id": 1,
            "message_id": "id-1",
            "message_type": "request",
            "direction": "client_to_server",
            "method": "tools/list",
            "params": None,
            "result": None,
            "error": None,
            "timestamp": "invalid_timestamp_str", # will raise Exception in datetime.fromtimestamp
            "latency_ms": 10.0,
        }
    ]
    with patch("mcp_debugger.storage.database.Database.connect", new_callable=AsyncMock):
        with patch("mcp_debugger.storage.database.Database.get_session", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {"id": 1}
            with patch("mcp_debugger.storage.database.Database.get_messages", new_callable=AsyncMock, return_value=mock_messages):
                with patch("mcp_debugger.storage.database.Database.get_errors", new_callable=AsyncMock, return_value=[]):
                    result = runner.invoke(app, ["inspect", "1"])
                    assert result.exit_code == 0
                    assert "invalid_timestamp_str" in result.stdout


# ===========================================================================
# 4. DOCTOR COMMAND EDGE CASES
# ===========================================================================

def test_doctor_python_version_check_fail(runner: CliRunner) -> None:
    """Verify doctor command fails if python version is < 3.11."""
    with patch("sys.version_info", (3, 10, 0)):
        with patch("shutil.which", return_value="some-path"):
            result = runner.invoke(app, ["doctor"])
            assert result.exit_code == 1
            assert "Python 3.11+ required" in result.stdout


def test_doctor_sqlite_version_fail_and_exceptions(runner: CliRunner) -> None:
    """Verify sqlite version check failure and exceptions handling."""
    # SQLite too old
    with patch("sqlite3.sqlite_version", "3.34.0"):
        with patch("shutil.which", return_value="some-path"):
            result = runner.invoke(app, ["doctor"])
            assert result.exit_code == 1
            assert "SQLite version < 3.35.0" in result.stdout

    # SQLite connection/ver check throws Exception
    # We patch sqlite3.sqlite_version in the sys.modules to raise Exception on attribute access
    mock_sqlite = MagicMock()
    type(mock_sqlite).sqlite_version = PropertyMock(side_effect=Exception("SQLite internal error"))
    with patch.dict("sys.modules", {"sqlite3": mock_sqlite}):
        with patch("shutil.which", return_value="some-path"):
            result = runner.invoke(app, ["doctor"])
            assert result.exit_code == 1
            assert "SQLite check failed" in result.stdout


def test_doctor_database_directories_and_permission_denied(runner: CliRunner) -> None:
    """Verify folder exists checking and permission checking fallback paths."""
    # Mock home folder path
    mock_home = Path("/fake/home")

    # Directory check: exists but no write permission
    with patch("pathlib.Path.home", return_value=mock_home):
        with patch("pathlib.Path.exists", return_value=True):
            with patch("os.access", return_value=False):
                with patch("shutil.which", return_value="some-path"):
                    result = runner.invoke(app, ["doctor"])
                    assert result.exit_code == 1
                    assert "permission denied" in result.stdout.lower()

    # Directory check: folder missing
    with patch("pathlib.Path.home", return_value=mock_home):
        with patch("pathlib.Path.exists", return_value=False):
            with patch("shutil.which", return_value="some-path"):
                result = runner.invoke(app, ["doctor"])
                assert result.exit_code == 1
                assert "missing – suggest running" in result.stdout


def test_doctor_permissions_and_schema_errors(runner: CliRunner) -> None:
    """Verify permissions too open warnings (Posix) and schema check failures."""
    
    # 1. Database file check: exists but permissions check throws exception
    class MockOSError:
        def __init__(self):
            self.name = "posix"
        def stat(self, *args, **kwargs):
            raise Exception("Stat error")
        def __getattr__(self, name):
            return getattr(os, name)

    mock_os = MockOSError()
    with patch.dict("sys.modules", {"os": mock_os}):
        with patch("shutil.which", return_value="some-path"):
            # Mock path to exist
            with patch("pathlib.Path.exists", return_value=True):
                result = runner.invoke(app, ["doctor"])
                assert "Failed to check DB file permissions" in result.stdout

    # 2. Database file check: exists but permission is not 600
    class MockOSTooOpen:
        def __init__(self):
            self.name = "posix"
        def stat(self, *args, **kwargs):
            mock_res = MagicMock()
            mock_res.st_mode = 0o777 # too open
            return mock_res
        def __getattr__(self, name):
            return getattr(os, name)

    mock_os_too_open = MockOSTooOpen()
    with patch.dict("sys.modules", {"os": mock_os_too_open}):
        with patch("shutil.which", return_value="some-path"):
            with patch("pathlib.Path.exists", return_value=True):
                result = runner.invoke(app, ["doctor"])
                assert "Permissions" in result.stdout
                assert "too open" in result.stdout

    # 3. Database schema check: connect throws Exception
    with patch("sqlite3.connect", side_effect=Exception("Connect DB error")):
        with patch("shutil.which", return_value="some-path"):
            with patch("pathlib.Path.exists", return_value=True):
                result = runner.invoke(app, ["doctor"])
                assert result.exit_code == 1
                assert "Database schema check failed" in result.stdout


def test_doctor_config_invalid_file(runner: CliRunner) -> None:
    """Verify doctor command shows config invalid when load raises exception."""
    with patch("mcp_debugger.config.Config.load", side_effect=Exception("TOML parsing error")):
        with patch("shutil.which", return_value="some-path"):
            with patch("pathlib.Path.exists", return_value=True):
                result = runner.invoke(app, ["doctor"])
                assert "config file: " in result.stdout.lower()
                assert "invalid" in result.stdout.lower()


def test_doctor_missing_binaries_and_sqlite(runner: CliRunner) -> None:
    """Verify doctor command output when binaries npx, node, git are missing or sqlite3 cannot be imported."""
    # 1. Missing binaries: shutil.which returns None
    with patch("shutil.which", return_value=None):
        with patch("pathlib.Path.exists", return_value=True):
            result = runner.invoke(app, ["doctor"])
            assert "npx not found" in result.stdout
            assert "Node.js not found" in result.stdout
            assert "git not found" in result.stdout

    # 2. SQLite not available (ImportError)
    with patch.dict("sys.modules", {"sqlite3": None}):
        with patch("shutil.which", return_value="some-path"):
            with patch("pathlib.Path.exists", return_value=True):
                result = runner.invoke(app, ["doctor"])
                assert result.exit_code == 1
                assert "SQLite not available" in result.stdout


# ===========================================================================
# 5. VALIDATE COMMAND EDGE CASES & COMPLIANCE SCORE
# ===========================================================================

def test_validate_mutual_exclusion(runner: CliRunner) -> None:
    """Verify validate command enforces mutual exclusion of arguments."""
    # Both provided
    result = runner.invoke(app, ["validate", "1", "--server", "dummy"])
    assert result.exit_code == 1
    assert "specify either a session_id or --server, not both" in result.stdout

    # Neither provided
    result2 = runner.invoke(app, ["validate"])
    assert result2.exit_code == 1
    assert "specify a session_id to validate or run a live server validation" in result2.stdout


def test_validate_live_exception(runner: CliRunner) -> None:
    """Verify live validation handles exceptions gracefully."""
    with patch("mcp_debugger.validate_live.run_live_validation", side_effect=Exception("Validation crash")):
        result = runner.invoke(app, ["validate", "--server", "dummy"])
        assert result.exit_code == 1
        assert "Error during live validation" in result.stdout


def test_validate_database_connect_failure(runner: CliRunner) -> None:
    """Verify validate handles DB connection errors."""
    with patch("mcp_debugger.storage.database.Database.connect", side_effect=Exception("Connect crash")):
        result = runner.invoke(app, ["validate", "1"])
        assert result.exit_code == 1
        assert "Error connecting to database" in result.stdout


def test_validate_session_not_found(runner: CliRunner) -> None:
    """Verify validate handles missing sessions."""
    with patch("mcp_debugger.storage.database.Database.connect", new_callable=AsyncMock):
        with patch("mcp_debugger.storage.database.Database.get_session", new_callable=AsyncMock, return_value=None):
            result = runner.invoke(app, ["validate", "999"])
            assert result.exit_code == 1
            assert "Session #999 not found" in result.stdout


def test_validate_engine_exception(runner: CliRunner) -> None:
    """Verify validate handles engine validation errors."""
    with patch("mcp_debugger.storage.database.Database.connect", new_callable=AsyncMock):
        with patch("mcp_debugger.storage.database.Database.get_session", new_callable=AsyncMock, return_value={"id": 1}):
            with patch("mcp_debugger.protocol.validator.ProtocolValidator.validate_session", side_effect=Exception("Engine crash")):
                result = runner.invoke(app, ["validate", "1"])
                assert result.exit_code == 1
                assert "Error validating session" in result.stdout


def test_calculate_compliance_score_logic() -> None:
    """Test calculate_compliance_score custom scoring mechanics."""
    # Critical failures causing 0% score
    startup_fail = [ValidationResult(rule_name="server_startup", passed=False, severity="critical", message="Fail")]
    score, passed, total = calculate_compliance_score(startup_fail)
    assert score == 0
    assert passed == 0
    assert total == 5

    # Test categorization rule sets
    res = [
        ValidationResult(rule_name="jsonrpc_version", passed=False, severity="critical", message="Fail"),
        ValidationResult(rule_name="envelope_type", passed=False, severity="critical", message="Fail"),
        ValidationResult(rule_name="initialize_first", passed=False, severity="critical", message="Fail"),
        ValidationResult(rule_name="handshake_order", passed=False, severity="critical", message="Fail"),
        ValidationResult(rule_name="tool_schema_validity", passed=False, severity="critical", message="Fail"),
    ]
    score, passed, total = calculate_compliance_score(res)
    assert score == 0
    assert passed == 0
    assert total == 5

    # Check mixed pass/fail with severity INFO/warning
    mixed = [
        ValidationResult(rule_name="jsonrpc_version", passed=True, severity="critical", message="Pass"),
        ValidationResult(rule_name="envelope_type", passed=False, severity="warning", message="Fail warning - doesn't count against critical score"),
    ]
    score, passed, total = calculate_compliance_score(mixed)
    assert score == 100
    assert passed == 5
    assert total == 5


def test_validate_rendering_info_severity(runner: CliRunner) -> None:
    """Verify validation CLI renders INFO severity correctly and supports JSON output."""
    mock_results = [
        ValidationResult(rule_name="custom_info", passed=False, severity="info", message="Some info message"),
        ValidationResult(rule_name="custom_warn", passed=False, severity="warning", message="Some warning message", suggestion="Fix this warning"),
        ValidationResult(rule_name="custom_pass", passed=True, severity="critical", message="Some pass message"),
    ]
    with patch("mcp_debugger.storage.database.Database.connect", new_callable=AsyncMock):
        with patch("mcp_debugger.storage.database.Database.get_session", new_callable=AsyncMock, return_value={"id": 1}):
            with patch("mcp_debugger.protocol.validator.ProtocolValidator.validate_session", new_callable=AsyncMock, return_value=mock_results):
                # Standard render mode (exits 0 as there is no critical error)
                result = runner.invoke(app, ["validate", "1"])
                assert result.exit_code == 0
                assert "INFO" in result.stdout
                assert "WARN" in result.stdout
                assert "✓ PASS" in result.stdout

                # JSON render mode
                result_json = runner.invoke(app, ["validate", "1", "--json"])
                assert result_json.exit_code == 0
                data = json.loads(result_json.stdout)
                assert len(data) == 3
                assert data[0]["rule_name"] == "custom_info"


def test_validate_keyboard_interrupt(runner: CliRunner) -> None:
    """Verify validate exits 0 on KeyboardInterrupt."""
    with patch("asyncio.run", side_effect=KeyboardInterrupt):
        result = runner.invoke(app, ["validate", "--server", "dummy"])
        assert result.exit_code == 0


# ===========================================================================
# 6. TOOLS COMMAND EDGE CASES
# ===========================================================================

def test_tools_database_error(runner: CliRunner) -> None:
    """Verify tools command exits on DB error."""
    with patch("mcp_debugger.storage.database.Database.connect", side_effect=sqlite3.DatabaseError("Corrupt DB")):
        result = runner.invoke(app, ["tools", "1"])
        assert result.exit_code == 1
        assert "corrupted or invalid" in result.stdout


def test_tools_general_connect_error(runner: CliRunner) -> None:
    """Verify tools command handles DB connect exceptions."""
    with patch("mcp_debugger.storage.database.Database.connect", side_effect=Exception("Connect crash")):
        result = runner.invoke(app, ["tools", "1"])
        assert result.exit_code == 1
        assert "Error connecting to database" in result.stdout


def test_tools_session_not_found(runner: CliRunner) -> None:
    """Verify tools command exits if session missing."""
    with patch("mcp_debugger.storage.database.Database.connect", new_callable=AsyncMock):
        with patch("mcp_debugger.storage.database.Database.get_session", new_callable=AsyncMock, return_value=None):
            result = runner.invoke(app, ["tools", "999"])
            assert result.exit_code == 1
            assert "Session 999 not found" in result.stdout


def test_tools_fetch_error(runner: CliRunner) -> None:
    """Verify tools command handles fetch query failures."""
    with patch("mcp_debugger.storage.database.Database.connect", new_callable=AsyncMock):
        with patch("mcp_debugger.storage.database.Database.get_session", new_callable=AsyncMock, return_value={"id": 1}):
            with patch("mcp_debugger.storage.database.Database.get_tools", new_callable=AsyncMock, side_effect=Exception("Query fail")):
                result = runner.invoke(app, ["tools", "1"])
                assert result.exit_code == 1
                assert "Error fetching tools" in result.stdout


def test_tools_empty_list(runner: CliRunner) -> None:
    """Verify tools output when no tools are discovered."""
    with patch("mcp_debugger.storage.database.Database.connect", new_callable=AsyncMock):
        with patch("mcp_debugger.storage.database.Database.get_session", new_callable=AsyncMock, return_value={"id": 1}):
            with patch("mcp_debugger.storage.database.Database.get_tools", new_callable=AsyncMock, return_value=[]):
                # Standard mode
                result = runner.invoke(app, ["tools", "1"])
                assert result.exit_code == 1
                assert "No tools discovered" in result.stdout

                # JSON mode
                result_json = runner.invoke(app, ["tools", "1", "--json"])
                assert result_json.exit_code == 1
                assert result_json.stdout.strip() == "[]"


def test_tools_details_and_exceptions(runner: CliRunner) -> None:
    """Verify tools detail query parameter and exception fallback logic."""
    mock_tools = [
        {
            "name": "my_tool",
            "description": "desc",
            "input_schema": '{"type": "object"}',
            "call_count": 5
        },
        {
            "name": "bad_schema_tool",
            "description": "desc",
            "input_schema": '{invalid-json}',
            "call_count": 2
        }
    ]

    with patch("mcp_debugger.storage.database.Database.connect", new_callable=AsyncMock):
        with patch("mcp_debugger.storage.database.Database.get_session", new_callable=AsyncMock, return_value={"id": 1}):
            with patch("mcp_debugger.storage.database.Database.get_tools", new_callable=AsyncMock, return_value=mock_tools):
                # 1. Non-existent tool requested
                result_missing = runner.invoke(app, ["tools", "1", "--detail", "missing_tool"])
                assert result_missing.exit_code == 1
                assert "not found in this session" in result_missing.stdout

                # 2. Tool with valid schema
                result_valid = runner.invoke(app, ["tools", "1", "--detail", "my_tool"])
                assert result_valid.exit_code == 0
                assert '"type": "object"' in result_valid.stdout

                # 3. Tool with invalid schema (JSON load exception fallback)
                result_invalid = runner.invoke(app, ["tools", "1", "--detail", "bad_schema_tool"])
                assert result_invalid.exit_code == 0
                assert '{invalid-json}' in result_invalid.stdout

                # 4. List tools with invalid schema to hit JSON load exception fallback in tools command
                result_list = runner.invoke(app, ["tools", "1"])
                assert result_list.exit_code == 0
                assert "bad_schema_tool" in result_list.stdout


def test_cli_helpers(runner: CliRunner) -> None:
    """Verify version, convert_utc_to_local_string, format_duration, truncate_command, get_status_text helpers."""
    from mcp_debugger.cli import (
        convert_utc_to_local_string,
        format_duration,
        truncate_command,
        get_status_text,
    )

    # 1. Version emoji encode exception fallback
    from rich.console import Console
    from unittest.mock import PropertyMock
    with patch.object(Console, "encoding", new_callable=PropertyMock, return_value="ascii"):
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        assert "MCP Debugger" in result.stdout

    # 2. convert_utc_to_local_string exception handling
    assert convert_utc_to_local_string("invalid-utc-time") == "invalid-utc-time"

    # 3. format_duration negative seconds, running status, and hour scaling
    assert format_duration(-10, "completed") == "0s"
    assert format_duration(4000, "completed") == "1h 6m 40s"
    assert format_duration(120, "running") == "2m 0s (running)"

    # 4. truncate_command
    assert truncate_command("a" * 100, max_len=50) == "a" * 47 + "..."

    # 5. get_status_text
    assert "running" in get_status_text("running").plain
    assert "completed" in get_status_text("completed").plain
    assert "failed" in get_status_text("failed").plain


def test_errors_command_database_exceptions(runner: CliRunner) -> None:
    """Verify that errors command handles database errors and exceptions gracefully."""
    # 1. connect DatabaseError
    with patch("mcp_debugger.storage.database.Database.connect", new_callable=AsyncMock) as mock_connect:
        mock_connect.side_effect = sqlite3.DatabaseError("Corrupt DB")
        result = runner.invoke(app, ["errors", "1"])
        assert result.exit_code == 1
        assert "corrupted or invalid" in result.stdout

    # 2. connect generic Exception
    with patch("mcp_debugger.storage.database.Database.connect", new_callable=AsyncMock) as mock_connect:
        mock_connect.side_effect = Exception("Connect error")
        result = runner.invoke(app, ["errors", "1"])
        assert result.exit_code == 1
        assert "Error connecting to database" in result.stdout

    # 3. get_errors exception fallback
    with patch("mcp_debugger.storage.database.Database.connect", new_callable=AsyncMock):
        with patch("mcp_debugger.storage.database.Database.get_session", new_callable=AsyncMock, return_value={"id": 1}):
            with patch("mcp_debugger.storage.database.Database.get_errors", new_callable=AsyncMock) as mock_get_errors:
                mock_get_errors.side_effect = Exception("Fetch failed")
                result = runner.invoke(app, ["errors", "1"])
                assert result.exit_code == 1
                assert "Error fetching errors" in result.stdout


# ===========================================================================
# 7. EXTENDED EDGE CASES & KEYBOARD INTERRUPTS
# ===========================================================================

def test_keyboard_interrupt_handlers(runner: CliRunner) -> None:
    """Verify that CLI commands exit cleanly on KeyboardInterrupt."""
    with patch("asyncio.run", side_effect=KeyboardInterrupt):
        for cmd in [
            ["list"],
            ["errors", "1"],
            ["validate", "1"],
            ["replay", "1", "--server", "dummy"],
            ["stats", "1"],
            ["inspect", "1"],
            ["export", "1"],
            ["compare", "1", "2"],
        ]:
            result = runner.invoke(app, cmd)
            assert result.exit_code == 0


def test_doctor_command_edge_cases(runner: CliRunner) -> None:
    """Verify doctor command runs and outputs diagnostic info."""
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    # Check that at least Python version check runs
    assert "Python version" in result.stdout


def test_validate_no_session_or_server(runner: CliRunner) -> None:
    """Verify that validate command fails if neither server nor session_id is specified."""
    result = runner.invoke(app, ["validate"])
    assert result.exit_code == 1
    assert "Please specify a session_id" in result.stdout or "Please specify a session_id" in result.stderr


def test_stats_command_extended_exceptions(runner: CliRunner) -> None:
    """Verify stats command connection error, ValueError, and file write exceptions."""
    # 1. Database connection error (line 1298-1300)
    with patch("mcp_debugger.storage.database.Database.connect", new_callable=AsyncMock) as mock_connect:
        mock_connect.side_effect = Exception("Conn Error")
        result = runner.invoke(app, ["stats", "1"])
        assert result.exit_code == 1
        assert "Error connecting to database" in result.stdout

    # 2. Session missing ValueError (line 1304-1307)
    with patch("mcp_debugger.storage.database.Database.connect", new_callable=AsyncMock):
        with patch("mcp_debugger.cli.aggregate_session_stats", new_callable=AsyncMock) as mock_agg:
            mock_agg.side_effect = ValueError("Session 1 not found")
            result = runner.invoke(app, ["stats", "1"])
            assert result.exit_code == 1
            assert "Session 1 not found" in result.stdout

    # 3. Stats calculation general Exception (line 1308-1311)
    with patch("mcp_debugger.storage.database.Database.connect", new_callable=AsyncMock):
        with patch("mcp_debugger.cli.aggregate_session_stats", new_callable=AsyncMock) as mock_agg:
            mock_agg.side_effect = Exception("Aggregation failure")
            result = runner.invoke(app, ["stats", "1"])
            assert result.exit_code == 1
            assert "Error aggregating statistics" in result.stdout

    # 4. JSON output file write failure (line 1320-1323)
    from mcp_debugger.analytics import SessionStats
    dummy_stats = SessionStats(
        session_id=1,
        friendly_name="sess",
        server_command="cmd",
        started_at="2026-06-20 12:00:00",
        ended_at=None,
        status="running",
        duration_seconds=None,
        total_messages=0,
        client_to_server_count=0,
        server_to_client_count=0,
        top_tools=[],
        errors_by_category={},
        latency_min=None,
        latency_max=None,
        latency_avg=None,
        latency_trend=[],
        method_distribution={},
        error_trend=[]
    )
    with patch("mcp_debugger.storage.database.Database.connect", new_callable=AsyncMock):
        with patch("mcp_debugger.cli.aggregate_session_stats", new_callable=AsyncMock, return_value=dummy_stats):
            with patch("pathlib.Path.write_text", side_effect=OSError("Write failed")):
                result = runner.invoke(app, ["stats", "1", "--json", "--output", "invalid/path.json"])
                assert result.exit_code == 0
                assert "Error writing to output file" in result.stdout

    # 5. Markdown/text output file write failure (line 1336-1337)
    with patch("mcp_debugger.storage.database.Database.connect", new_callable=AsyncMock):
        with patch("mcp_debugger.cli.aggregate_session_stats", new_callable=AsyncMock, return_value=dummy_stats):
            with patch("pathlib.Path.write_text", side_effect=OSError("Write failed")):
                result = runner.invoke(app, ["stats", "1", "--output", "invalid/path.md"])
                assert result.exit_code == 0
                assert "Error writing output file" in result.stdout


def test_stats_command_no_data_fallbacks(runner: CliRunner) -> None:
    """Verify stats command renders placeholder text when session data is missing/empty."""
    from mcp_debugger.analytics import SessionStats
    empty_stats = SessionStats(
        session_id=1,
        friendly_name="sess",
        server_command="cmd",
        started_at="2026-06-20 12:00:00",
        ended_at=None,
        status="running",
        duration_seconds=None,
        total_messages=0,
        client_to_server_count=0,
        server_to_client_count=0,
        top_tools=[],
        errors_by_category={},
        latency_min=None,
        latency_max=None,
        latency_avg=None,
        latency_trend=[],
        method_distribution={},
        error_trend=[]
    )
    with patch("mcp_debugger.storage.database.Database.connect", new_callable=AsyncMock):
        with patch("mcp_debugger.cli.aggregate_session_stats", new_callable=AsyncMock, return_value=empty_stats):
            result = runner.invoke(app, ["stats", "1"])
            assert result.exit_code == 0
            assert "No tools called" in result.stdout
            assert "No latency data" in result.stdout
            assert "No errors recorded" in result.stdout
            assert "No methods recorded" in result.stdout
            assert "No responses recorded to track errors" in result.stdout


def test_compare_command_extended_exceptions(runner: CliRunner) -> None:
    """Verify compare command connection, ValueError, Exception and color formatting logic."""
    # 1. Connection error (line 1451-1453)
    with patch("mcp_debugger.storage.database.Database.connect", new_callable=AsyncMock) as mock_connect:
        mock_connect.side_effect = Exception("Conn Error")
        result = runner.invoke(app, ["compare", "1", "2"])
        assert result.exit_code == 1
        assert "Error connecting to database" in result.stdout

    # 2. ValueError (missing session - line 1458-1461)
    with patch("mcp_debugger.storage.database.Database.connect", new_callable=AsyncMock):
        with patch("mcp_debugger.cli.aggregate_session_stats", new_callable=AsyncMock) as mock_agg:
            mock_agg.side_effect = ValueError("Session 1 not found")
            result = runner.invoke(app, ["compare", "1", "2"])
            assert result.exit_code == 1
            assert "Session 1 not found" in result.stdout

    # 3. General stats aggregation exception (line 1462-1465)
    with patch("mcp_debugger.storage.database.Database.connect", new_callable=AsyncMock):
        with patch("mcp_debugger.cli.aggregate_session_stats", new_callable=AsyncMock) as mock_agg:
            mock_agg.side_effect = Exception("General error")
            result = runner.invoke(app, ["compare", "1", "2"])
            assert result.exit_code == 1
            assert "Error aggregating session statistics" in result.stdout


def test_compare_command_color_and_summary_logic(runner: CliRunner) -> None:
    """Verify compare command outputs correct formatting and summaries for various diffs."""
    from mcp_debugger.analytics import SessionStats, ToolMetric
    
    stats_a = SessionStats(
        session_id=1,
        friendly_name="sess-a",
        server_command="cmd",
        started_at="2026-06-20 12:00:00",
        ended_at="2026-06-20 12:05:00",
        status="completed",
        duration_seconds=300,
        total_messages=10,
        client_to_server_count=5,
        server_to_client_count=5,
        top_tools=[ToolMetric(name="my-tool", calls=5, avg_latency_ms=10.0, errors_count=0, error_rate=0.0)],
        errors_by_category={"protocol": 5},
        latency_min=10.0,
        latency_max=200.0,
        latency_avg=100.0,
        latency_trend=[100.0] * 5,
        method_distribution={"tools/call": 5},
        error_trend=[0] * 5
    )

    # Session B is slower (350s, +16.7%), has more errors (protocol: 10), my-tool calls increased (+3 calls), latency slower (+30%)
    stats_b = SessionStats(
        session_id=2,
        friendly_name="sess-b",
        server_command="cmd",
        started_at="2026-06-20 12:00:00",
        ended_at="2026-06-20 12:05:50",
        status="completed",
        duration_seconds=350,
        total_messages=12,
        client_to_server_count=6,
        server_to_client_count=6,
        top_tools=[ToolMetric(name="my-tool", calls=8, avg_latency_ms=13.0, errors_count=1, error_rate=0.125)],
        errors_by_category={"protocol": 10},
        latency_min=10.0,
        latency_max=200.0,
        latency_avg=100.0,
        latency_trend=[100.0] * 5,
        method_distribution={"tools/call": 5},
        error_trend=[0] * 5
    )

    with patch("mcp_debugger.storage.database.Database.connect", new_callable=AsyncMock):
        with patch("mcp_debugger.cli.aggregate_session_stats", new_callable=AsyncMock) as mock_agg:
            mock_agg.side_effect = [stats_a, stats_b]
            result = runner.invoke(app, ["compare", "1", "2"])
            assert result.exit_code == 0
            assert "is slower" in result.stdout
            assert "has more errors" in result.stdout
            assert "slower" in result.stdout
            assert "regression" in result.stdout

    # Session C is faster (200s, -33.3%), has fewer errors (protocol: 1), my-tool calls decreased (-3 calls), latency faster (-30%), and a tool is removed
    stats_c = SessionStats(
        session_id=3,
        friendly_name="sess-c",
        server_command="cmd",
        started_at="2026-06-20 12:00:00",
        ended_at="2026-06-20 12:03:20",
        status="completed",
        duration_seconds=200,
        total_messages=8,
        client_to_server_count=4,
        server_to_client_count=4,
        top_tools=[], # my-tool removed
        errors_by_category={"protocol": 1},
        latency_min=10.0,
        latency_max=200.0,
        latency_avg=100.0,
        latency_trend=[100.0] * 5,
        method_distribution={"tools/call": 5},
        error_trend=[0] * 5
    )

    with patch("mcp_debugger.storage.database.Database.connect", new_callable=AsyncMock):
        with patch("mcp_debugger.cli.aggregate_session_stats", new_callable=AsyncMock) as mock_agg:
            mock_agg.side_effect = [stats_a, stats_c]
            result = runner.invoke(app, ["compare", "1", "3"])
            assert result.exit_code == 0
            assert "is faster" in result.stdout
            assert "has fewer errors" in result.stdout
            assert "tool" in result.stdout
            assert "removed" in result.stdout
            assert "improvement" in result.stdout


def test_export_command_extended_exceptions(runner: CliRunner) -> None:
    """Verify export command connection exceptions, stats exceptions, and file writing errors."""
    # 1. Connection error
    with patch("mcp_debugger.storage.database.Database.connect", new_callable=AsyncMock) as mock_connect:
        mock_connect.side_effect = Exception("Conn error")
        result = runner.invoke(app, ["export", "1"])
        assert result.exit_code == 1
        assert "Error connecting to database" in result.stdout

    # 2. Stats computation exception — patch at the source module since cli imports it locally
    with patch("mcp_debugger.storage.database.Database.connect", new_callable=AsyncMock):
        with patch("mcp_debugger.storage.database.Database.get_session", new_callable=AsyncMock, return_value={"id": 1}):
            with patch("mcp_debugger.analytics.aggregate_session_stats", new_callable=AsyncMock) as mock_agg:
                mock_agg.side_effect = Exception("Stats error")
                result = runner.invoke(app, ["export", "1"])
                assert result.exit_code == 1
                assert "Error computing session stats" in result.stdout

    # 3. Output file write error — mock the JSONExporter.export to raise OSError
    with patch("mcp_debugger.storage.database.Database.connect", new_callable=AsyncMock):
        with patch("mcp_debugger.storage.database.Database.get_session", new_callable=AsyncMock, return_value={"id": 1}):
            with patch("mcp_debugger.analytics.aggregate_session_stats", new_callable=AsyncMock):
                with patch("mcp_debugger.exporters.json_exporter.JSONExporter.export", side_effect=OSError("Write permission denied")):
                    result = runner.invoke(app, ["export", "1", "--output", "readonly/file.json"])
                    assert result.exit_code == 1
                    assert "Error writing to readonly/file.json" in result.stdout


def test_export_command_otlp(runner: CliRunner) -> None:
    """Verify OTLP exporter code paths and failure handling in export command."""
    # 1. Mock OTLPExporter import error (simulate module not installed)
    with patch("mcp_debugger.storage.database.Database.connect", new_callable=AsyncMock):
        with patch("mcp_debugger.storage.database.Database.get_session", new_callable=AsyncMock, return_value={"id": 1}):
            with patch("mcp_debugger.analytics.aggregate_session_stats", new_callable=AsyncMock):
                with patch.dict("sys.modules", {"mcp_debugger.exporters.otlp_exporter": None}):
                    result = runner.invoke(app, ["export", "1", "--format", "otlp"])
                    assert result.exit_code == 1
                    assert "otlp_exporter" in result.stdout or "otlp_exporter" in result.stderr

    # 2. Mock OTLPExporter successful export
    mock_exporter = MagicMock()
    mock_exporter.return_value.export.return_value = 5
    with patch("mcp_debugger.storage.database.Database.connect", new_callable=AsyncMock):
        with patch("mcp_debugger.storage.database.Database.get_session", new_callable=AsyncMock, return_value={"id": 1}):
            with patch("mcp_debugger.analytics.aggregate_session_stats", new_callable=AsyncMock):
                with patch("mcp_debugger.exporters.otlp_exporter.OTLPExporter", mock_exporter):
                    result = runner.invoke(app, ["export", "1", "--format", "otlp"])
                    assert result.exit_code == 0
                    assert "Exported 5 span(s)" in result.stdout

    # 3. Mock OTLPExporter exception
    mock_exporter_fail = MagicMock()
    mock_exporter_fail.return_value.export.side_effect = RuntimeError("Network error")
    with patch("mcp_debugger.storage.database.Database.connect", new_callable=AsyncMock):
        with patch("mcp_debugger.storage.database.Database.get_session", new_callable=AsyncMock, return_value={"id": 1}):
            with patch("mcp_debugger.analytics.aggregate_session_stats", new_callable=AsyncMock):
                with patch("mcp_debugger.exporters.otlp_exporter.OTLPExporter", mock_exporter_fail):
                    result = runner.invoke(app, ["export", "1", "--format", "otlp"])
                    assert result.exit_code == 0
                    assert "OTLP export failed" in result.stdout


def _make_replay_result(**kwargs):
    """Helper to build a valid ReplayResult with required fields."""
    from datetime import datetime, timezone
    from mcp_debugger.replay.engine import ReplayResult
    defaults = dict(
        session_id=1,
        target_server_command="dummy",
        started_at=datetime(2026, 6, 20, 12, 0, 0, tzinfo=timezone.utc),
        ended_at=datetime(2026, 6, 20, 12, 0, 1, tzinfo=timezone.utc),
        total_messages_replayed=1,
        successful_responses=1,
        failed_responses=0,
        mismatched_responses=0,
        timed_out=0,
        messages=[],
    )
    defaults.update(kwargs)
    return ReplayResult(**defaults)


def _make_replayed_message(**kwargs):
    """Helper to build a valid ReplayedMessage with required fields."""
    from mcp_debugger.replay.engine import ReplayedMessage
    defaults = dict(
        original_message_id=1,
        method="initialize",
        request_sent={"method": "initialize"},
        latency_ms=5.0,
        matches=True,
    )
    defaults.update(kwargs)
    return ReplayedMessage(**defaults)


def test_replay_command_extended_edge_cases(runner: CliRunner) -> None:
    """Verify replay command alias lookup failures, missing servers, connection/session failures, format_payload corner cases, server crashes, OTLP exporters, and file write errors."""
    from mcp_debugger.config import Config

    # 1. Alias lookup failure (line 1786-1789)
    with patch("mcp_debugger.config.get_config") as mock_get_cfg:
        cfg = Config()
        cfg.data = {"aliases": {"dev": "npx echo"}}
        mock_get_cfg.return_value = cfg
        result = runner.invoke(app, ["replay", "1", "--alias", "nonexistent"])
        assert result.exit_code == 1
        assert "Alias 'nonexistent' not found in config" in result.stdout

    # 2. No server specified error (line 1793-1796)
    with patch("mcp_debugger.config.get_config") as mock_get_cfg:
        cfg = Config()
        cfg.data = {} # empty config
        mock_get_cfg.return_value = cfg
        result = runner.invoke(app, ["replay", "1"])
        assert result.exit_code == 1
        assert "Error: No server specified" in result.stdout

    # 3. Mock a database connection failure for replay (line 1822-1824)
    with patch("mcp_debugger.storage.database.Database.connect", new_callable=AsyncMock) as mock_connect:
        mock_connect.side_effect = Exception("Conn Error")
        result = runner.invoke(app, ["replay", "1", "--server", "dummy"])
        assert result.exit_code == 1
        assert "Error connecting to database" in result.stdout

    # 4. Missing session error for replay (line 1828-1830)
    with patch("mcp_debugger.storage.database.Database.connect", new_callable=AsyncMock):
        with patch("mcp_debugger.storage.database.Database.get_session", new_callable=AsyncMock, return_value=None):
            result = runner.invoke(app, ["replay", "1", "--server", "dummy"])
            assert result.exit_code == 1
            assert "Session #1 not found" in result.stdout

    # 5. Server crashed during replay
    crashed_msg = _make_replayed_message(
        original_message_id=42,
        method="tools/call",
        request_sent={"method": "tools/call", "params": {}},
        matches=False,
        error="Write error: pipe closed",
        latency_ms=12.34,
    )
    mock_result_crash = _make_replay_result(
        total_messages_replayed=1,
        successful_responses=0,
        failed_responses=1,
        mismatched_responses=0,
        timed_out=0,
        messages=[crashed_msg],
    )
    with patch("mcp_debugger.storage.database.Database.connect", new_callable=AsyncMock):
        with patch("mcp_debugger.storage.database.Database.get_session", new_callable=AsyncMock, return_value={"server_command": "dummy"}):
            with patch("mcp_debugger.replay.engine.ReplayEngine.replay", new_callable=AsyncMock, return_value=mock_result_crash):
                result = runner.invoke(app, ["replay", "1", "--server", "dummy"])
                assert result.exit_code == 2
                assert "Server crashed during message #42" in result.stdout

    # 6. JSON output file write failure in replay
    mock_result_ok = _make_replay_result(
        successful_responses=1,
        messages=[_make_replayed_message()],
    )
    with patch("mcp_debugger.storage.database.Database.connect", new_callable=AsyncMock):
        with patch("mcp_debugger.storage.database.Database.get_session", new_callable=AsyncMock, return_value={"server_command": "dummy"}):
            with patch("mcp_debugger.replay.engine.ReplayEngine.replay", new_callable=AsyncMock, return_value=mock_result_ok):
                with patch("pathlib.Path.write_text", side_effect=OSError("Write failed")):
                    result = runner.invoke(app, ["replay", "1", "--server", "dummy", "--json", "--output", "invalid/path.json"])
                    assert result.exit_code == 1
                    assert "Error writing output to" in result.stdout

    # 7. Terminal output file write failure in replay (line 2019-2021)
    with patch("mcp_debugger.storage.database.Database.connect", new_callable=AsyncMock):
        with patch("mcp_debugger.storage.database.Database.get_session", new_callable=AsyncMock, return_value={"server_command": "dummy"}):
            with patch("mcp_debugger.replay.engine.ReplayEngine.replay", new_callable=AsyncMock, return_value=mock_result_ok):
                with patch("pathlib.Path.write_text", side_effect=OSError("Write failed")):
                    result = runner.invoke(app, ["replay", "1", "--server", "dummy", "--output", "invalid/path.txt"])
                    assert result.exit_code == 1
                    assert "Error writing output to" in result.stdout

    # 8. OTLP replay export exceptions (lines 2029-2041)
    # Check OTLP import error via sys.modules
    with patch("mcp_debugger.storage.database.Database.connect", new_callable=AsyncMock):
        with patch("mcp_debugger.storage.database.Database.get_session", new_callable=AsyncMock, return_value={"server_command": "dummy"}):
            with patch("mcp_debugger.replay.engine.ReplayEngine.replay", new_callable=AsyncMock, return_value=mock_result_ok):
                with patch.dict("sys.modules", {"mcp_debugger.exporters.otlp_replay_exporter": None}):
                    result = runner.invoke(app, ["replay", "1", "--server", "dummy", "--otlp-export"])
                    assert result.exit_code == 0
                    assert "Warning" in result.stdout

    # Check OTLP general error during export
    mock_otlp_replay_exporter = MagicMock()
    mock_otlp_replay_exporter.return_value.export.side_effect = Exception("Export network fail")
    with patch("mcp_debugger.storage.database.Database.connect", new_callable=AsyncMock):
        with patch("mcp_debugger.storage.database.Database.get_session", new_callable=AsyncMock, return_value={"server_command": "dummy"}):
            with patch("mcp_debugger.replay.engine.ReplayEngine.replay", new_callable=AsyncMock, return_value=mock_result_ok):
                with patch("mcp_debugger.exporters.otlp_replay_exporter.OTLPReplayExporter", mock_otlp_replay_exporter):
                    result = runner.invoke(app, ["replay", "1", "--server", "dummy", "--otlp-export"])
                    assert result.exit_code == 0
                    assert "Warning: OTLP export failed" in result.stdout


def test_replay_mismatch_formatting_and_no_diff(runner: CliRunner) -> None:
    """Verify replay command detailed mismatch reports and --no-diff mismatched IDs list."""
    mismatched_msg = _make_replayed_message(
        original_message_id=7,
        method="tools/call",
        request_sent={"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "test_tool", "arguments": {"x": 1}}},
        original_response=None,
        replayed_response={"result": "different"},
        matches=False,
        latency_ms=10.0,
        diff_text="Result mismatch",
    )
    mock_result_mismatch = _make_replay_result(
        total_messages_replayed=1,
        successful_responses=0,
        failed_responses=0,
        mismatched_responses=1,
        messages=[mismatched_msg],
    )

    # With diff (default)
    with patch("mcp_debugger.storage.database.Database.connect", new_callable=AsyncMock):
        with patch("mcp_debugger.storage.database.Database.get_session", new_callable=AsyncMock, return_value={"server_command": "dummy"}):
            with patch("mcp_debugger.replay.engine.ReplayEngine.replay", new_callable=AsyncMock, return_value=mock_result_mismatch):
                result = runner.invoke(app, ["replay", "1", "--server", "dummy"])
                assert result.exit_code == 1
                assert "Tool: test_tool" in result.stdout
                assert "Arguments:" in result.stdout
                assert "Original response:" in result.stdout
                assert "None" in result.stdout
                assert "Replayed response:" in result.stdout
                assert "different" in result.stdout
                assert "Differences:" in result.stdout

    # With --no-diff (line 2009-2011)
    with patch("mcp_debugger.storage.database.Database.connect", new_callable=AsyncMock):
        with patch("mcp_debugger.storage.database.Database.get_session", new_callable=AsyncMock, return_value={"server_command": "dummy"}):
            with patch("mcp_debugger.replay.engine.ReplayEngine.replay", new_callable=AsyncMock, return_value=mock_result_mismatch):
                result = runner.invoke(app, ["replay", "1", "--server", "dummy", "--no-diff"])
                assert result.exit_code == 1
                assert "Mismatched Message IDs: [7]" in result.stdout
                assert "Differences:" not in result.stdout


def test_inspect_non_json_fields(runner: CliRunner) -> None:
    """Verify that inspect processes non-JSON message fields without raising an exception."""
    with patch("mcp_debugger.storage.database.Database.connect", new_callable=AsyncMock):
        with patch("mcp_debugger.storage.database.Database.get_session", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {"id": 1, "friendly_name": "test"}
            with patch("mcp_debugger.storage.database.Database.get_messages", new_callable=AsyncMock) as mock_messages:
                mock_messages.return_value = [
                    {
                        "id": 1,
                        "direction": "client_to_server",
                        "message_type": "request",
                        "method": "foo",
                        "params": "{invalid-json}",
                        "result": "{invalid-json}",
                        "error": "{invalid-json}",
                        "timestamp": 123.45
                    }
                ]
                result = runner.invoke(app, ["inspect", "1"])
                assert result.exit_code == 0


