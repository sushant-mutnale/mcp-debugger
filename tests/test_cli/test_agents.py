"""Unit tests for mcp-debugger agents CLI command."""

import asyncio
import json
from typer.testing import CliRunner

from mcp_debugger.cli import app
from mcp_debugger.storage.database import Database


def test_agents_command_missing_session(mock_db_path: str, runner: CliRunner) -> None:
    """Verify agents command when session ID does not exist."""
    result = runner.invoke(app, ["agents", "9999"])
    assert result.exit_code == 1
    assert "Session 9999 not found" in result.stdout


def test_agents_command_empty_session(mock_db_path: str, runner: CliRunner) -> None:
    """Verify agents command when session exists but has no agents registered."""

    async def setup_empty() -> int:
        db = Database(db_path=mock_db_path)
        await db.connect()
        sid = await db.create_session("empty-agent-session")
        await db.close()
        return sid

    sid = asyncio.run(setup_empty())

    # Text mode
    result = runner.invoke(app, ["agents", str(sid)])
    assert result.exit_code == 0
    assert "no agents" in result.stdout.lower()

    # JSON mode
    result_json = runner.invoke(app, ["agents", str(sid), "--json"])
    assert result_json.exit_code == 0
    data = json.loads(result_json.stdout)
    assert data["session_id"] == sid
    assert data["agents"] == []
    assert data["hierarchy"] == []
    assert data["handoffs"] == []


def test_agents_command_tree_visualization(mock_db_path: str, runner: CliRunner) -> None:
    """Verify hierarchy tree rendering with roles and frameworks."""

    async def setup_tree() -> int:
        db = Database(db_path=mock_db_path)
        await db.connect()
        sid = await db.create_session("hierarchy-session")
        aid_pm = await db.create_agent(
            sid, name="ProjectManager", role="Lead", framework="crewai"
        )
        aid_dev = await db.create_agent(
            sid, name="Developer", role="Coder", parent_agent_id=aid_pm, framework="crewai"
        )
        await db.create_agent(
            sid, name="Tester", role="QA", parent_agent_id=aid_dev, framework="crewai"
        )
        await db.close()
        return sid

    sid = asyncio.run(setup_tree())

    # Default view (--tree)
    result = runner.invoke(app, ["agents", str(sid)])
    assert result.exit_code == 0
    assert "ProjectManager" in result.stdout
    assert "Developer" in result.stdout
    assert "Tester" in result.stdout
    assert "Lead" in result.stdout
    assert "Coder" in result.stdout
    assert "QA" in result.stdout
    assert "crewai" in result.stdout


def test_agents_command_handoffs_table(mock_db_path: str, runner: CliRunner) -> None:
    """Verify handoffs table rendering."""

    async def setup_handoffs() -> int:
        db = Database(db_path=mock_db_path)
        await db.connect()
        sid = await db.create_session("handoff-session")
        aid_pm = await db.create_agent(sid, name="PM", role="lead")
        await db.create_agent(sid, name="Dev", role="coder", parent_agent_id=aid_pm)

        # Log handoff step
        await db.log_step(
            sid,
            0,
            "handoff",
            "PM",
            json.dumps({
                "from_agent": "PM",
                "to_agent": "Dev",
                "task": "Build Authentication Module",
                "transferred_context": {"spec": "OAuth2"},
            }),
            json.dumps({
                "to_agent": "Dev",
                "output_context": {"status": "in_progress"},
            }),
            latency_ms=125.5,
            agent_id=aid_pm,
        )
        await db.close()
        return sid

    sid = asyncio.run(setup_handoffs())

    result = runner.invoke(app, ["agents", str(sid), "--handoffs"])
    assert result.exit_code == 0
    assert "PM" in result.stdout
    assert "Dev" in result.stdout
    assert "Build Authentication Module" in result.stdout
    assert "125.5" in result.stdout or "125" in result.stdout


def test_agents_command_json_mode(mock_db_path: str, runner: CliRunner) -> None:
    """Verify structured JSON output mode."""

    async def setup_full() -> int:
        db = Database(db_path=mock_db_path)
        await db.connect()
        sid = await db.create_session("json-session")
        aid_pm = await db.create_agent(sid, name="PM", role="lead")
        await db.create_agent(sid, name="Dev", role="coder", parent_agent_id=aid_pm)

        await db.log_step(
            sid,
            0,
            "handoff",
            "PM",
            json.dumps({
                "from_agent": "PM",
                "to_agent": "Dev",
                "task": "OAuth Spec",
            }),
            json.dumps({"status": "delegated"}),
            latency_ms=45.0,
            agent_id=aid_pm,
        )
        await db.close()
        return sid

    sid = asyncio.run(setup_full())

    result = runner.invoke(app, ["agents", str(sid), "--json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["session_id"] == sid
    assert len(data["agents"]) == 2
    assert len(data["hierarchy"]) == 1
    assert data["hierarchy"][0]["name"] == "PM"
    assert len(data["hierarchy"][0]["children"]) == 1
    assert data["hierarchy"][0]["children"][0]["name"] == "Dev"
    assert len(data["handoffs"]) == 1
    assert data["handoffs"][0]["from_agent"] == "PM"
    assert data["handoffs"][0]["to_agent"] == "Dev"
    assert data["handoffs"][0]["task"] == "OAuth Spec"
