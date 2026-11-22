"""Unit tests for mcp-debugger live TUI dashboard CLI command."""

import asyncio
import json
from typer.testing import CliRunner

from mcp_debugger.cli import app
from mcp_debugger.storage.database import Database


def test_live_command_once_with_sample_session(mock_db_path: str, runner: CliRunner) -> None:
    """Verify live --once displays Live Session Monitor, agent name, and tool name."""

    async def setup_session() -> int:
        db = Database(db_path=mock_db_path)
        await db.connect()
        sid = await db.create_session("python test_server.py", server_name="sample-server")
        aid = await db.create_agent(sid, name="Coordinator", role="Orchestrator")
        await db.log_step(
            sid,
            0,
            "thought",
            "Coordinator",
            "Planning query execution",
            "Plan ready",
            agent_id=aid,
        )
        await db.log_step(
            sid,
            1,
            "tool_call",
            "Coordinator",
            json.dumps({"tool": "search_db", "args": {"query": "SELECT 1"}}),
            "Rows returned",
            agent_id=aid,
            tokens_input=100,
            tokens_output=50,
            latency_ms=42.5,
        )
        await db.close()
        return sid

    sid = asyncio.run(setup_session())

    result = runner.invoke(app, ["live", str(sid), "--once"])
    assert result.exit_code == 0
    assert ("Live Session Monitor" in result.stdout) or ("Live Monitor" in result.stdout)
    assert "Coordinator" in result.stdout
    assert "search_db" in result.stdout


def test_live_command_missing_session(mock_db_path: str, runner: CliRunner) -> None:
    """Verify live --once reports error or non-zero exit code when session does not exist."""
    result = runner.invoke(app, ["live", "999", "--once"])
    assert result.exit_code != 0
    assert "not found" in result.stdout.lower() or "error" in result.stdout.lower()


def test_live_command_default_latest_session(mock_db_path: str, runner: CliRunner) -> None:
    """Verify live --once without session_id defaults to the latest session."""

    async def setup_session() -> int:
        db = Database(db_path=mock_db_path)
        await db.connect()
        sid = await db.create_session("python test_server.py", server_name="sample-server")
        aid = await db.create_agent(sid, name="Coordinator", role="Orchestrator")
        await db.log_step(
            sid,
            0,
            "tool_call",
            "Coordinator",
            json.dumps({"tool": "search_db", "args": {}}),
            "Done",
            agent_id=aid,
        )
        await db.close()
        return sid

    asyncio.run(setup_session())

    result = runner.invoke(app, ["live", "--once"])
    assert result.exit_code == 0
    assert "Coordinator" in result.stdout
    assert "search_db" in result.stdout


def test_live_command_no_sessions_empty_db(mock_db_path: str, runner: CliRunner) -> None:
    """Verify live --once on empty DB exits with non-zero code."""
    result = runner.invoke(app, ["live", "--once"])
    assert result.exit_code != 0


def test_dashboard_unit_fetch_and_build(mock_db_path: str) -> None:
    """Unit test LiveDashboard components directly."""
    from rich.console import Console
    from mcp_debugger.live import LiveDashboard

    async def run_unit() -> None:
        db = Database(db_path=mock_db_path)
        await db.connect()
        sid = await db.create_session("python test_server.py", server_name="sample-server")
        aid_parent = await db.create_agent(sid, name="LeadAgent", role="Orchestrator")
        aid_child = await db.create_agent(
            sid, name="WorkerAgent", role="Worker", parent_agent_id=aid_parent
        )
        await db.log_step(
            sid,
            0,
            "llm_call",
            "LeadAgent",
            "Prompt",
            "Response",
            agent_id=aid_parent,
            tokens_input=1000,
            tokens_output=500,
            latency_ms=150.0,
        )
        await db.log_step(
            sid,
            1,
            "tool_call",
            "WorkerAgent",
            json.dumps({"name": "compute", "parameters": {"x": 10}}),
            "42",
            agent_id=aid_child,
            tokens_input=200,
            tokens_output=100,
            latency_ms=50.0,
        )
        await db.close()

        console = Console(record=True, width=120)
        dash = LiveDashboard(sid, db_path=mock_db_path, console=console)

        state = await dash.fetch_state()
        assert state["session"] is not None
        assert len(state["agents"]) == 2
        assert len(state["hierarchy"]) == 1
        assert len(state["steps"]) == 2
        assert state["total_tokens"] == 1800
        assert state["total_cost"] > 0

        header = dash.build_header(state)
        assert header is not None

        tree = dash.build_agent_tree(state)
        assert tree is not None

        table = dash.build_event_table(state)
        assert table is not None

        layout = dash.build_layout(state)
        assert layout is not None

        await dash.render_once()
        output = console.export_text()
        assert "LeadAgent" in output
        assert "WorkerAgent" in output
        assert "compute" in output

    asyncio.run(run_unit())


def test_dashboard_unit_empty_session(mock_db_path: str) -> None:
    """Unit test LiveDashboard components on a session with no agents or steps."""
    from rich.console import Console
    from mcp_debugger.live import LiveDashboard

    async def run_unit() -> None:
        db = Database(db_path=mock_db_path)
        await db.connect()
        sid = await db.create_session("empty-server")
        await db.close()

        console = Console(record=True, width=120)
        dash = LiveDashboard(sid, db_path=mock_db_path, console=console)
        await dash.render_once()
        output = console.export_text()
        assert "Live Session Monitor" in output
        assert "No agents registered" in output
        assert "No steps recorded" in output

    asyncio.run(run_unit())


def test_dashboard_unit_missing_session(mock_db_path: str) -> None:
    """Unit test LiveDashboard with missing session exits with 1."""
    import pytest
    from rich.console import Console
    from mcp_debugger.live import LiveDashboard

    async def run_unit() -> None:
        console = Console(record=True)
        dash = LiveDashboard(9999, db_path=mock_db_path, console=console)
        with pytest.raises(SystemExit) as exc_info:
            await dash.render_once()
        assert exc_info.value.code == 1

    asyncio.run(run_unit())


def test_dashboard_unit_run_loop(mock_db_path: str) -> None:
    """Unit test LiveDashboard run polling loop terminates cleanly."""
    from rich.console import Console
    from mcp_debugger.live import LiveDashboard

    async def run_unit() -> None:
        db = Database(db_path=mock_db_path)
        await db.connect()
        sid = await db.create_session("loop-server")
        await db.close()

        console = Console(record=True, width=100)
        dash = LiveDashboard(sid, db_path=mock_db_path, console=console, refresh_rate=0.05)

        task = asyncio.create_task(dash.run())
        await asyncio.sleep(0.1)
        dash.stop()
        await task

    asyncio.run(run_unit())

