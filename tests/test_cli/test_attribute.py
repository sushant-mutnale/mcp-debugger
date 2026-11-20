"""Unit tests for mcp-debugger attribute CLI command."""

import asyncio
import json
from typer.testing import CliRunner

from mcp_debugger.cli import app
from mcp_debugger.storage.database import Database


def test_attribute_command_missing_session(mock_db_path: str, runner: CliRunner) -> None:
    """Verify attribute command when session ID does not exist."""
    result = runner.invoke(app, ["attribute", "9999"])
    assert result.exit_code == 1
    assert "Session 9999 not found" in result.stdout


def test_attribute_command_clean_session(mock_db_path: str, runner: CliRunner) -> None:
    """Verify attribute command on a clean session."""

    async def setup_clean() -> int:
        db = Database(db_path=mock_db_path)
        await db.connect()
        sid = await db.create_session("clean-agent")
        await db.log_step(sid, 0, "thought", "agent", "Plan", "Starting task")
        await db.log_step(
            sid,
            1,
            "tool_call",
            "agent",
            json.dumps({"tool": "ping", "args": {}}),
            "pong",
        )
        await db.close()
        return sid

    sid = asyncio.run(setup_clean())

    # Text mode
    result = runner.invoke(app, ["attribute", str(sid)])
    assert result.exit_code == 0
    assert "clean" in result.stdout.lower() or "none" in result.stdout.lower()

    # JSON mode
    result_json = runner.invoke(app, ["attribute", str(sid), "--json"])
    assert result_json.exit_code == 0
    data = json.loads(result_json.stdout)
    assert data["category"] == "none"
    assert data["point_of_commitment"] is None


def test_attribute_command_loop_failure(mock_db_path: str, runner: CliRunner) -> None:
    """Verify attribute command on a trajectory with a tool loop failure."""

    async def setup_loop() -> int:
        db = Database(db_path=mock_db_path)
        await db.connect()
        sid = await db.create_session("looping-agent")
        await db.log_step(sid, 0, "thought", "bot", "Plan", "Checking status")
        for i in range(1, 4):
            await db.log_step(
                sid,
                i,
                "tool_call",
                "bot",
                json.dumps({"tool": "check_status", "args": ["id-1"]}),
                "pending",
                deduplicate=False,
            )
        await db.close()
        return sid

    sid = asyncio.run(setup_loop())

    # Rich formatting mode
    result = runner.invoke(app, ["attribute", str(sid)])
    assert result.exit_code == 0
    # Must display PoC, boundary badge, and timeline
    assert "POINT OF COMMITMENT" in result.stdout or "Point of Commitment" in result.stdout
    assert "AGENT" in result.stdout
    assert "check_status" in result.stdout

    # JSON mode
    result_json = runner.invoke(app, ["attribute", str(sid), "--json"])
    assert result_json.exit_code == 0
    data = json.loads(result_json.stdout)
    assert data["category"] == "agent"
    assert data["point_of_commitment"] is not None
    assert data["point_of_commitment"]["step_index"] == 1
    assert data["point_of_commitment"]["tool_name"] == "check_status"


def test_attribute_command_live_flag(mock_db_path: str, runner: CliRunner) -> None:
    """Verify attribute command with --live flag."""

    async def setup_session() -> int:
        db = Database(db_path=mock_db_path)
        await db.connect()
        sid = await db.create_session("live-test")
        await db.log_step(
            sid,
            0,
            "tool_call",
            "bot",
            json.dumps({"tool": "fetch", "args": {}}),
            json.dumps({"content": []}),
        )
        await db.log_step(
            sid,
            1,
            "thought",
            "bot",
            "process",
            "Error: IndexError: list index out of range",
        )
        await db.close()
        return sid

    sid = asyncio.run(setup_session())

    result = runner.invoke(app, ["attribute", str(sid), "--live", "--max-steps", "2", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert "preflight" in data or "point_of_commitment" in data or "category" in data
