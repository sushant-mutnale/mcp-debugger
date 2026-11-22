"""Tests for Multi-Agent Flow & Topology web API endpoints."""

import json

import pytest
from fastapi.testclient import TestClient

from mcp_debugger.storage.database import Database
from mcp_debugger.web.app import app


@pytest.mark.asyncio
async def test_get_session_agents_success(mock_db_path: str) -> None:
    """Verify GET /api/sessions/{session_id}/agents returns hierarchy, handoffs, and stats."""
    db = Database(db_path=mock_db_path)
    await db.connect()

    session_id = await db.create_session("multi-agent-session")

    # Seed agents
    coord_id = await db.create_agent(
        session_id=session_id,
        name="Coordinator",
        role="planner",
        framework="crewai",
    )
    reviewer_id = await db.create_agent(
        session_id=session_id,
        name="CodeReviewer",
        role="reviewer",
        parent_agent_id=coord_id,
        framework="crewai",
    )

    # Seed handoff step and work step
    await db.log_step(
        session_id=session_id,
        step_index=0,
        step_type="handoff",
        agent_name="Coordinator",
        agent_id=coord_id,
        input_data=json.dumps({
            "from_agent": "Coordinator",
            "to_agent": "CodeReviewer",
            "task": "Review authentication refactor",
        }),
        output_data=json.dumps({"status": "accepted"}),
        tokens_input=120,
        tokens_output=60,
        latency_ms=45.2,
    )
    await db.log_step(
        session_id=session_id,
        step_index=1,
        step_type="llm_call",
        agent_name="CodeReviewer",
        agent_id=reviewer_id,
        input_data=json.dumps({"model": "gpt-4o", "prompt": "Check security"}),
        output_data=json.dumps({"response": "Looks good"}),
        tokens_input=300,
        tokens_output=150,
        latency_ms=120.5,
    )

    await db.close()

    with TestClient(app) as client:
        resp = client.get(f"/api/sessions/{session_id}/agents")
        assert resp.status_code == 200

        data = resp.json()
        assert data["session_id"] == session_id
        assert len(data["agents"]) == 2

        # Verify hierarchy
        assert len(data["hierarchy"]) == 1
        root = data["hierarchy"][0]
        assert root["name"] == "Coordinator"
        assert len(root["children"]) == 1
        assert root["children"][0]["name"] == "CodeReviewer"

        # Verify handoffs
        assert len(data["handoffs"]) == 1
        handoff = data["handoffs"][0]
        assert handoff["from_agent"] == "Coordinator"
        assert handoff["to_agent"] == "CodeReviewer"
        assert handoff["task"] == "Review authentication refactor"
        assert handoff["latency_ms"] == pytest.approx(45.2)

        # Verify agent stats
        stats = data["agent_stats"]
        assert "Coordinator" in stats
        assert "CodeReviewer" in stats

        assert stats["Coordinator"]["steps"] == 1
        assert stats["Coordinator"]["tokens"] == 180
        assert stats["Coordinator"]["latency_sum"] == pytest.approx(45.2)
        assert isinstance(stats["Coordinator"]["cost"], (float, int))

        assert stats["CodeReviewer"]["steps"] == 1
        assert stats["CodeReviewer"]["tokens"] == 450
        assert stats["CodeReviewer"]["latency_sum"] == pytest.approx(120.5)
        assert stats["CodeReviewer"]["cost"] > 0


@pytest.mark.asyncio
async def test_get_session_agents_empty(mock_db_path: str) -> None:
    """Verify GET /api/sessions/{session_id}/agents returns empty structures when no agents exist."""
    db = Database(db_path=mock_db_path)
    await db.connect()
    session_id = await db.create_session("empty-agent-session")
    await db.close()

    with TestClient(app) as client:
        resp = client.get(f"/api/sessions/{session_id}/agents")
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == session_id
        assert data["agents"] == []
        assert data["hierarchy"] == []
        assert data["handoffs"] == []
        assert data["agent_stats"] == {}


@pytest.mark.asyncio
async def test_get_session_agents_not_found(mock_db_path: str) -> None:
    """Verify GET /api/sessions/{session_id}/agents returns 404 for nonexistent session."""
    with TestClient(app) as client:
        resp = client.get("/api/sessions/999999/agents")
        assert resp.status_code == 404
        assert "Session not found" in resp.json()["detail"] or "999999 not found" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_get_session_agents_robust_fallbacks(mock_db_path: str) -> None:
    """Verify non-dict handoff payloads and steps with null agent_name fallback cleanly."""
    db = Database(db_path=mock_db_path)
    await db.connect()

    session_id = await db.create_session("robust-session")
    agent_id = await db.create_agent(
        session_id=session_id,
        name="AutoAgent",
        role="worker",
    )

    # Step with non-dict JSON input (e.g. list [1, 2, 3]) and null agent_name but agent_id set
    await db.log_step(
        session_id=session_id,
        step_index=0,
        step_type="handoff",
        agent_name=None,
        agent_id=agent_id,
        input_data="[1, 2, 3]",
        output_data="scalars",
        tokens_input=50,
        tokens_output=25,
        latency_ms=15.0,
    )

    # Step with completely invalid string input and null agent_name but agent_id set
    await db.log_step(
        session_id=session_id,
        step_index=1,
        step_type="llm_call",
        agent_name=None,
        agent_id=agent_id,
        input_data="not json at all",
        tokens_input=100,
        tokens_output=50,
        latency_ms=30.0,
    )

    await db.close()

    with TestClient(app) as client:
        resp = client.get(f"/api/sessions/{session_id}/agents")
        assert resp.status_code == 200
        data = resp.json()

        # agent_stats resolved from agent_id
        stats = data["agent_stats"]
        assert "AutoAgent" in stats
        assert stats["AutoAgent"]["steps"] == 2
        assert stats["AutoAgent"]["tokens"] == 225

        # handoff resolved from agent_id without error on non-dict payload
        assert len(data["handoffs"]) == 1
        h = data["handoffs"][0]
        assert h["from_agent"] == "AutoAgent"
        assert h["to_agent"] == "unknown"


def test_session_detail_html_renders_agents_tab() -> None:
    """Verify session_detail.html contains the Multi-Agent tab button and panel containers."""
    with TestClient(app) as client:
        resp = client.get("/session/1")
        assert resp.status_code == 200
        html = resp.text
        assert 'data-tab="agents"' in html
        assert "🤖 Multi-Agent Flow" in html
        assert 'id="tab-agents"' in html
        assert 'id="agentCanvas"' in html
        assert 'id="handoffListContainer"' in html
        assert 'id="handoffList"' in html

