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
