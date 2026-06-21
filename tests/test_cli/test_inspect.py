import time
import json
import asyncio
from typing import Any
from unittest.mock import patch
from typer.testing import CliRunner

from mcp_debugger.cli import app
from mcp_debugger.storage.database import Database


def test_inspect_command_missing_session(mock_db_path: str, runner: CliRunner) -> None:
    """Verify inspect command when session ID does not exist."""
    result = runner.invoke(app, ["inspect", "9999"])
    assert result.exit_code == 1
    assert "Session 9999 not found" in result.stdout


def test_inspect_command_empty_session(mock_db_path: str, runner: CliRunner) -> None:
    """Verify inspect command when session exists but has no messages."""

    async def create_empty() -> None:
        db = Database(db_path=mock_db_path)
        await db.connect()
        await db.create_session("dummy")
        await db.close()

    asyncio.run(create_empty())
    result = runner.invoke(app, ["inspect", "1"])
    assert result.exit_code == 0
    assert "No messages" in result.stdout


def test_inspect_command_populated(mock_db_path: str, tmp_path: Any, runner: CliRunner) -> None:
    """Verify inspect command with populated messages in default, JSON, and file output modes."""

    async def populate() -> None:
        db = Database(db_path=mock_db_path)
        await db.connect()
        session_id = await db.create_session("dummy")

        # Request
        await db.log_message(
            session_id,
            "client_to_server",
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        )
        # Success Response
        time.sleep(0.01)
        await db.log_message(
            session_id,
            "server_to_client",
            {"jsonrpc": "2.0", "id": 1, "result": {"tools": [{"name": "my_tool"}]}},
        )
        # Notification
        await db.log_message(
            session_id,
            "client_to_server",
            {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {"ok": True}},
        )
        # Error response
        await db.log_message(
            session_id,
            "server_to_client",
            {"jsonrpc": "2.0", "id": 2, "error": {"code": -32601, "message": "Method not found"}},
        )
        await db.close()

    asyncio.run(populate())

    # 1. Default UI inspect output checks
    result = runner.invoke(app, ["inspect", "1"])
    assert result.exit_code == 0
    assert "client → server" in result.stdout
    assert "server → client" in result.stdout
    assert "tools/list" in result.stdout
    assert "notifications/initialized" in result.stdout
    assert "Method not found" in result.stdout
    assert "+" in result.stdout  # latency badge
    assert "ms" in result.stdout  # latency badge unit

    # 2. Filter --method initialize (should find none since method is notifications/initialized and tools/list)
    result_filter_method = runner.invoke(app, ["inspect", "1", "--method", "tools/list"])
    assert result_filter_method.exit_code == 0
    assert "tools/list" in result_filter_method.stdout
    assert "notifications/initialized" not in result_filter_method.stdout

    # 3. Filter --direction client_to_server
    result_filter_dir = runner.invoke(app, ["inspect", "1", "--direction", "client_to_server"])
    assert result_filter_dir.exit_code == 0
    assert "tools/list" in result_filter_dir.stdout
    assert "notifications/initialized" in result_filter_dir.stdout
    assert "Method not found" not in result_filter_dir.stdout

    # 4. Filter --search
    result_search = runner.invoke(app, ["inspect", "1", "--search", "my_tool"])
    assert result_search.exit_code == 0
    assert "my_tool" in result_search.stdout
    assert "notifications/initialized" not in result_search.stdout

    # 5. Pagination --limit 1 --offset 1 (second message, i.e., tools/list response)
    result_page = runner.invoke(app, ["inspect", "1", "--limit", "1", "--offset", "1"])
    assert result_page.exit_code == 0
    assert "tools/list" in result_page.stdout
    assert "result" in result_page.stdout
    assert "notifications/initialized" not in result_page.stdout

    # 6. JSON mode
    result_json = runner.invoke(app, ["inspect", "1", "--json"])
    assert result_json.exit_code == 0
    parsed = json.loads(result_json.stdout)
    assert len(parsed) == 4
    assert parsed[0]["direction"] == "client_to_server"
    assert parsed[0]["method"] == "tools/list"
    assert parsed[1]["direction"] == "server_to_client"
    assert parsed[1]["latency_ms"] is not None
    assert parsed[1]["latency_ms"] >= 0
    assert parsed[3]["error"]["code"] == -32601

    # 7. File output mode (JSON)
    out_file = tmp_path / "out.json"
    result_out = runner.invoke(app, ["inspect", "1", "--json", "--output", str(out_file)])
    assert result_out.exit_code == 0
    assert out_file.exists()
    file_content = out_file.read_text(encoding="utf-8")
    parsed_file = json.loads(file_content)
    assert len(parsed_file) == 4

    # 8. File output mode (Terminal Plain/Text)
    out_txt = tmp_path / "out.txt"
    result_out_txt = runner.invoke(app, ["inspect", "1", "--output", str(out_txt)])
    assert result_out_txt.exit_code == 0
    assert out_txt.exists()
    txt_content = out_txt.read_text(encoding="utf-8")
    assert "client → server" in txt_content
    assert "tools/list" in txt_content


def test_doctor_command_success(tmp_path: Any, runner: CliRunner) -> None:
    """Verify doctor command passes when environment is healthy."""
    db_dir = tmp_path / ".mcp-debugger"
    db_dir.mkdir(parents=True, exist_ok=True)

    with (
        patch("pathlib.Path.home", return_value=tmp_path),
        patch("sys.version_info", (3, 11, 2)),
        patch("shutil.which", return_value="/usr/bin/mock-bin"),
    ):
        result = runner.invoke(app, ["doctor"])
        assert result.exit_code == 0
        assert "Python version:" in result.stdout
        assert "SQLite version:" in result.stdout
        assert "Database directory:" in result.stdout
        assert "npx command found:" in result.stdout


def test_doctor_command_critical_failure(tmp_path: Any, runner: CliRunner) -> None:
    """Verify doctor command fails with exit code 1 when Python is outdated or database directory is missing/not writable."""
    # 1. Outdated Python version check
    with (
        patch("pathlib.Path.home", return_value=tmp_path),
        patch("sys.version_info", (3, 9, 0)),
    ):
        result = runner.invoke(app, ["doctor"])
        assert result.exit_code == 1
        assert "Python 3.11+ required" in result.stdout

    # 2. Database directory not writable or missing
    with (
        patch("pathlib.Path.home", return_value=tmp_path),
        patch("sys.version_info", (3, 12, 0)),
        patch("pathlib.Path.exists", return_value=False),
    ):
        result = runner.invoke(app, ["doctor"])
        assert result.exit_code == 1
        assert "missing" in result.stdout


def test_tools_command_errors(mock_db_path: str, runner: CliRunner) -> None:
    """Verify tools command exits with 1 on invalid session or when session has no tools."""
    # 1. Invalid session
    result = runner.invoke(app, ["tools", "9999"])
    assert result.exit_code == 1
    assert "Session 9999 not found" in result.stdout

    # 2. Session exists but has no tools
    async def populate() -> None:
        db = Database(db_path=mock_db_path)
        await db.connect()
        await db.create_session("my_server", friendly_name="empty-session")
        await db.close()

    asyncio.run(populate())

    result_empty = runner.invoke(app, ["tools", "1"])
    assert result_empty.exit_code == 1
    assert "No tools discovered in this session" in result_empty.stdout

    # 3. JSON mode on empty tools
    result_empty_json = runner.invoke(app, ["tools", "1", "--json"])
    assert result_empty_json.exit_code == 1
    assert result_empty_json.stdout.strip() == "[]"


def test_tools_command_populated(mock_db_path: str, runner: CliRunner) -> None:
    """Verify tools command displays discovered tools list, detailed schema, and usage statistics."""

    async def populate() -> None:
        db = Database(db_path=mock_db_path)
        await db.connect()
        # Create session
        session_id = await db.create_session("my_server", friendly_name="tools-session")

        # Discovered tools
        await db.log_tool(
            session_id,
            {
                "name": "calculate",
                "description": "Evaluate math expression",
                "inputSchema": {"type": "object", "properties": {"expr": {"type": "string"}}},
            },
        )
        await db.log_tool(
            session_id,
            {
                "name": "format_text",
                "description": "Align strings",
                "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}},
            },
        )

        # Log calls
        # 2 calls to calculate
        await db.log_message(
            session_id,
            "client_to_server",
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "calculate", "arguments": {"expr": "2+2"}},
            },
        )
        await db.log_message(
            session_id,
            "client_to_server",
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "calculate", "arguments": {"expr": "3*3"}},
            },
        )
        # 1 call to format_text
        await db.log_message(
            session_id,
            "client_to_server",
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "format_text", "arguments": {"text": "hello"}},
            },
        )
        await db.close()

    asyncio.run(populate())

    # 1. Plain table output check
    result = runner.invoke(app, ["tools", "1"])
    assert result.exit_code == 0
    assert "Tools discovered in session #1" in result.stdout
    assert "calculate" in result.stdout
    assert "Evaluate math expression" in result.stdout
    assert "format_text" in result.stdout
    assert "Align strings" in result.stdout
    # Check calls counts are displayed
    assert "2" in result.stdout
    assert "1" in result.stdout

    # 2. JSON mode check
    result_json = runner.invoke(app, ["tools", "1", "--json"])
    assert result_json.exit_code == 0
    parsed = json.loads(result_json.stdout)
    assert len(parsed) == 2
    assert parsed[0]["name"] == "calculate"
    assert parsed[0]["calls"] == 2
    assert parsed[0]["input_schema"]["properties"]["expr"]["type"] == "string"
    assert parsed[1]["name"] == "format_text"
    assert parsed[1]["calls"] == 1

    # 3. Detail schema check
    result_detail = runner.invoke(app, ["tools", "1", "--detail", "calculate"])
    assert result_detail.exit_code == 0
    assert "Tool Schema: calculate" in result_detail.stdout
    assert "expr" in result_detail.stdout

    # 4. Detail schema JSON check
    result_detail_json = runner.invoke(app, ["tools", "1", "--detail", "calculate", "--json"])
    assert result_detail_json.exit_code == 0
    parsed_detail = json.loads(result_detail_json.stdout)
    assert parsed_detail["properties"]["expr"]["type"] == "string"

    # 5. Detail schema invalid tool
    result_detail_invalid = runner.invoke(app, ["tools", "1", "--detail", "non_existent"])
    assert result_detail_invalid.exit_code == 1
    assert "Tool non_existent not found" in result_detail_invalid.stdout


def test_errors_command_missing_session(mock_db_path: str, runner: CliRunner) -> None:
    """Verify errors command output when session ID does not exist."""
    result = runner.invoke(app, ["errors", "9999"])
    assert result.exit_code == 1
    assert "Session 9999 not found" in result.stdout


def test_errors_command_empty_session(mock_db_path: str, runner: CliRunner) -> None:
    """Verify errors command when session exists but has no errors."""
    async def create_empty() -> None:
        db = Database(db_path=mock_db_path)
        await db.connect()
        await db.create_session("dummy")
        await db.close()

    asyncio.run(create_empty())
    result = runner.invoke(app, ["errors", "1"])
    assert result.exit_code == 0
    assert "No classified errors found" in result.stdout

    result_json = runner.invoke(app, ["errors", "1", "--json"])
    assert result_json.exit_code == 0
    assert result_json.stdout.strip() == "[]"


def test_errors_command_populated(mock_db_path: str, runner: CliRunner) -> None:
    """Verify errors command lists, filters, and formats classified errors."""
    async def populate() -> None:
        db = Database(db_path=mock_db_path)
        await db.connect()
        session_id = await db.create_session("dummy")

        # 1. Log a protocol error
        await db.log_error(
            session_id=session_id,
            message_id=None,
            error_type="protocol",
            error_message="Method not found: foo",
            suggestion="check spelling",
            error_code=-32601,
        )

        # 2. Log a tool execution error
        await db.log_error(
            session_id=session_id,
            message_id=None,
            error_type="tool_execution",
            error_message="Permission denied reading file",
            suggestion="check permissions",
            error_code=None,
        )
        await db.close()

    asyncio.run(populate())

    # Plain table output check
    result = runner.invoke(app, ["errors", "1"])
    assert result.exit_code == 0
    assert "Classified Errors for Session 1" in result.stdout
    assert "PROTOCOL" in result.stdout
    assert "Method not found: foo" in result.stdout
    assert "check spelling" in result.stdout
    assert "TOOL_EXECUTION" in result.stdout
    assert "Permission denied reading file" in result.stdout
    assert "check permissions" in result.stdout

    # Category filter check
    result_filter = runner.invoke(app, ["errors", "1", "--category", "protocol"])
    assert result_filter.exit_code == 0
    assert "PROTOCOL" in result_filter.stdout
    assert "TOOL_EXECUTION" not in result_filter.stdout

    # JSON mode check
    result_json = runner.invoke(app, ["errors", "1", "--json"])
    assert result_json.exit_code == 0
    parsed = json.loads(result_json.stdout)
    assert len(parsed) == 2
    assert parsed[0]["error_type"] == "protocol"
    assert parsed[0]["error_code"] == -32601
    assert parsed[1]["error_type"] == "tool_execution"
    assert parsed[1]["suggestion"] == "check permissions"


def test_inspect_shows_classified_errors(mock_db_path: str, runner: CliRunner) -> None:
    """Verify that inspect command renders classified error badge and suggestion dynamically or from DB."""
    async def populate() -> None:
        db = Database(db_path=mock_db_path)
        await db.connect()
        session_id = await db.create_session("dummy")

        # Log a request
        await db.log_message(
            session_id=session_id,
            direction="client_to_server",
            message={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {}},
        )

        # Log a response containing an error
        msg_id = await db.log_message(
            session_id=session_id,
            direction="server_to_client",
            message={"jsonrpc": "2.0", "id": 1, "error": {"code": -32601, "message": "Method not found"}},
        )

        # Log the classified error referencing the message
        await db.log_error(
            session_id=session_id,
            message_id=msg_id,
            error_type="protocol",
            error_message="Method not found",
            suggestion="Check spelling. Did you mean 'tools/list'?",
            error_code=-32601,
        )
        await db.close()

    asyncio.run(populate())

    result = runner.invoke(app, ["inspect", "1"])
    assert result.exit_code == 0
    assert "PROTOCOL ERROR" in result.stdout
    assert "💡 Suggestion: Check spelling" in result.stdout
