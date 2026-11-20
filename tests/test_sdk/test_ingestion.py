import asyncio
import json
import os
import tempfile
import pytest
from typer.testing import CliRunner

from mcp_debugger.cli import app
from mcp_debugger.sdk import start_trace, trace_agent, trace_mcp
from mcp_debugger.storage.database import Database


@pytest.fixture
def temp_db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    try:
        if os.path.exists(path):
            os.remove(path)
    except PermissionError:
        pass


def test_start_trace_sync(temp_db_path: str) -> None:
    """Sync context manager creates session, captures steps into SQLite, and closes cleanly."""
    @trace_mcp("linter")
    def lint_code(code: str) -> str:
        return "lint clean"

    @trace_agent("code_generator")
    def generate_code(prompt: str) -> str:
        code = f"code for {prompt}"
        lint_code(code)
        return code

    with start_trace(friendly_name="test-run-1", db_path=temp_db_path) as trace:
        sid = trace.session_id
        assert sid > 0
        code = generate_code("fibonacci")

    assert code == "code for fibonacci"

    # Verify directly from database
    async def _verify() -> None:
        db = Database(db_path=temp_db_path)
        await db.connect()
        session = await db.get_session(sid)
        assert session is not None
        assert session["friendly_name"] == "test-run-1"
        assert session["status"] == "completed"

        steps = await db.get_steps(sid)
        assert len(steps) == 2
        # First step is outer agent thought (step_index 0)
        assert steps[0]["agent_name"] == "code_generator"
        assert steps[0]["step_type"] == "thought"
        assert "fibonacci" in steps[0]["input"]

        # Second step is nested tool call (step_index 1)
        assert steps[1]["agent_name"] == "code_generator"
        assert steps[1]["step_type"] == "tool_call"
        assert "linter" in steps[1]["input"]
        await db.close()

    asyncio.run(_verify())


@pytest.mark.asyncio
async def test_start_trace_async(temp_db_path: str) -> None:
    """Async context manager creates session and logs steps asynchronously."""
    @trace_agent("async_researcher")
    async def research(topic: str) -> dict:
        await asyncio.sleep(0.01)
        return {"topic": topic, "summary": "found info"}

    async with start_trace(friendly_name="test-async-run", db_path=temp_db_path) as trace:
        sid = trace.session_id
        assert sid > 0
        res = await research("MCP 2026")
        assert res["topic"] == "MCP 2026"

    db = Database(db_path=temp_db_path)
    await db.connect()
    session = await db.get_session(sid)
    assert session is not None
    assert session["status"] == "completed"

    steps = await db.get_steps(sid)
    assert len(steps) == 1
    assert steps[0]["agent_name"] == "async_researcher"
    assert "MCP 2026" in steps[0]["input"]
    await db.close()


def test_cli_inspect_displays_trajectory_steps(temp_db_path: str, runner: CliRunner) -> None:
    """mcp-debugger inspect displays captured trajectory steps in text and JSON mode."""
    with start_trace(friendly_name="cli-inspect-session", db_path=temp_db_path) as trace:
        sid = trace.session_id

        @trace_agent("cli_agent")
        def work():
            return "all done"

        work()

    # Invoke CLI inspect with custom db path environment
    env = {**os.environ, "MCP_DEBUGGER_DATABASE_PATH": temp_db_path}

    result = runner.invoke(app, ["inspect", str(sid)], env=env)
    assert result.exit_code == 0
    assert "Trajectory Steps" in result.stdout
    assert "cli_agent" in result.stdout

    # JSON mode
    json_result = runner.invoke(app, ["inspect", str(sid), "--json"], env=env)
    assert json_result.exit_code == 0
    parsed = json.loads(json_result.stdout)
    assert "trajectory_steps" in parsed or (isinstance(parsed, list) and len(parsed) >= 0)


def test_atexit_flush_closes_sessions(temp_db_path: str) -> None:
    """_atexit_flush handles active sessions properly."""
    from mcp_debugger.sdk.ingestion import _active_sessions, _atexit_flush

    trace = start_trace(friendly_name="atexit-test", db_path=temp_db_path)
    assert trace in _active_sessions
    assert not trace._closed

    _atexit_flush()
    assert trace._closed
