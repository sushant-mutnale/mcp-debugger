"""Tests for CLI commands."""

import asyncio
import json
import os
from typing import Any, Generator, Optional
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from mcp_debugger.cli import app
from mcp_debugger.storage.database import Database

runner = CliRunner()


@pytest.fixture
def mock_db_path(tmp_path: Any) -> Generator[str, None, None]:
    """Fixture to mock the Database path to use a temporary file for isolation."""
    temp_db_file = tmp_path / "test_sessions.db"
    original_init = Database.__init__

    def mock_init(self: Any, db_path: Optional[str] = None) -> None:
        original_init(self, db_path=str(temp_db_file))

    with patch("mcp_debugger.storage.database.Database.__init__", mock_init):
        yield str(temp_db_file)


def test_version() -> None:
    """Test that the version command prints correct version info."""
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "v0.1.0" in result.stdout


def test_list_command_empty(mock_db_path: str) -> None:
    """Verify list command output when database has no sessions."""
    if os.path.exists(mock_db_path):
        os.remove(mock_db_path)

    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert "No sessions found" in result.stdout

    result_json = runner.invoke(app, ["list", "--json"])
    assert result_json.exit_code == 0
    assert result_json.stdout.strip() == "[]"


def test_list_command_populated(mock_db_path: str) -> None:
    """Verify list command displays sessions in table and JSON format."""

    async def populate() -> None:
        db = Database(db_path=mock_db_path)
        await db.connect()
        s1 = await db.create_session("cat --verbose", friendly_name="session-one")
        s2 = await db.create_session("echo 'hello'", friendly_name="session-two")
        await db.close_session(s1, "completed")
        await db.close_session(s2, "error")
        await db.close()

    asyncio.run(populate())

    # Test pretty table mode (passing columns env to prevent narrow terminal truncation by Rich)
    result = runner.invoke(app, ["list"], env={"COLUMNS": "120"})
    assert result.exit_code == 0
    assert "session-one" in result.stdout
    assert "session-two" in result.stdout
    assert "cat --verbose" in result.stdout
    assert "completed" in result.stdout
    assert "error" in result.stdout

    # Test filter by status
    result_filter = runner.invoke(app, ["list", "--status", "completed"], env={"COLUMNS": "120"})
    assert result_filter.exit_code == 0
    assert "session-one" in result_filter.stdout
    assert "session-two" not in result_filter.stdout

    # Test limit
    result_limit = runner.invoke(app, ["list", "--limit", "1"], env={"COLUMNS": "120"})
    assert result_limit.exit_code == 0
    assert "session-two" in result_limit.stdout
    assert "session-one" not in result_limit.stdout

    # Test JSON mode
    result_json = runner.invoke(app, ["list", "--json"], env={"COLUMNS": "120"})
    assert result_json.exit_code == 0
    data = json.loads(result_json.stdout)
    assert len(data) == 2
    assert data[0]["name"] == "session-two"
    assert data[0]["server_command"] == "echo 'hello'"
    assert data[0]["status"] == "error"
    assert data[1]["name"] == "session-one"


def test_list_command_corrupted(mock_db_path: str) -> None:
    """Verify list command output when database is corrupted."""
    with open(mock_db_path, "w") as f:
        f.write("corrupted database file gibberish")

    result = runner.invoke(app, ["list"], env={"COLUMNS": "120"})
    assert result.exit_code == 1
    assert "corrupted or invalid" in result.stdout
    assert "Recovery Suggestion" in result.stdout


def test_proxy_command_with_name(mock_db_path: str) -> None:
    """Verify that proxy command accepts and records the session friendly name."""
    from unittest.mock import AsyncMock

    with patch("mcp_debugger.cli.StdioProxy.run", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = 0
        result = runner.invoke(app, ["proxy", "--server", "cat", "--name", "test-friendly-name"])
        assert result.exit_code == 0

    async def verify() -> Optional[str]:
        db = Database(db_path=mock_db_path)
        await db.connect()
        sessions = await db.get_sessions()
        await db.close()
        if sessions:
            val = sessions[0]["friendly_name"]
            return str(val) if val is not None else None
        return None

    name = asyncio.run(verify())
    assert name == "test-friendly-name"


def test_inspect_command_missing_session(mock_db_path: str) -> None:
    """Verify inspect command when session ID does not exist."""
    result = runner.invoke(app, ["inspect", "9999"])
    assert result.exit_code == 1
    assert "Session 9999 not found" in result.stdout


def test_inspect_command_empty_session(mock_db_path: str) -> None:
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


def test_inspect_command_populated(mock_db_path: str, tmp_path: Any) -> None:
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

    import time

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
