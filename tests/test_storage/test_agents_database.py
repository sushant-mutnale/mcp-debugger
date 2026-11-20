"""Unit tests for SQLite multi-agent hierarchy storage and query APIs."""

import pytest

from mcp_debugger.storage.database import Database


@pytest.mark.asyncio
async def test_create_and_get_agent(mock_db_path: str) -> None:
    """Create an agent record and retrieve it with deserialized metadata."""
    db = Database(db_path=mock_db_path)
    await db.connect()

    session_id = await db.create_session("multi-agent-session")

    aid = await db.create_agent(
        session_id=session_id,
        name="LeadOrchestrator",
        role="planner",
        framework="crewai",
        metadata={"skills": ["planning", "delegation"]},
    )
    assert aid > 0

    agent = await db.get_agent(aid)
    assert agent is not None
    assert agent["id"] == aid
    assert agent["session_id"] == session_id
    assert agent["name"] == "LeadOrchestrator"
    assert agent["role"] == "planner"
    assert agent["framework"] == "crewai"
    assert agent["parent_agent_id"] is None
    assert isinstance(agent["metadata"], dict)
    assert agent["metadata"]["skills"] == ["planning", "delegation"]

    await db.close()


@pytest.mark.asyncio
async def test_agent_parent_child_hierarchy(mock_db_path: str) -> None:
    """Verify recursive parent-child tree assembly for multi-level agent delegation."""
    db = Database(db_path=mock_db_path)
    await db.connect()

    session_id = await db.create_session("tree-session")

    # Root
    aid_root = await db.create_agent(
        session_id=session_id,
        name="RootCoordinator",
        role="coordinator",
    )
    # Level 1 children
    aid_researcher = await db.create_agent(
        session_id=session_id,
        name="Researcher",
        role="data_gatherer",
        parent_agent_id=aid_root,
    )
    aid_coder = await db.create_agent(
        session_id=session_id,
        name="Coder",
        role="programmer",
        parent_agent_id=aid_root,
    )
    # Level 2 grandchild
    aid_reviewer = await db.create_agent(
        session_id=session_id,
        name="Reviewer",
        role="code_reviewer",
        parent_agent_id=aid_coder,
    )

    assert aid_researcher > aid_root
    assert aid_coder > aid_root
    assert aid_reviewer > aid_coder

    # Test flat list
    agents = await db.get_agents(session_id)
    assert len(agents) == 4

    # Test recursive tree
    tree = await db.get_agent_hierarchy(session_id)
    assert len(tree) == 1
    root = tree[0]
    assert root["name"] == "RootCoordinator"
    assert len(root["children"]) == 2

    # Find Coder in root's children
    coder_node = next(c for c in root["children"] if c["name"] == "Coder")
    assert len(coder_node["children"]) == 1
    reviewer_node = coder_node["children"][0]
    assert reviewer_node["name"] == "Reviewer"
    assert len(reviewer_node["children"]) == 0

    await db.close()


@pytest.mark.asyncio
async def test_agent_cascade_delete_on_session_removal(mock_db_path: str) -> None:
    """Agents are removed when parent session is deleted."""
    db = Database(db_path=mock_db_path)
    await db.connect()

    session_id = await db.create_session("temp-session")
    aid = await db.create_agent(session_id=session_id, name="TempAgent")
    assert await db.get_agent(aid) is not None

    conn = await db._get_conn()
    await conn.execute("PRAGMA foreign_keys = ON;")
    await conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    await conn.commit()

    assert await db.get_agent(aid) is None
    await db.close()


@pytest.mark.asyncio
async def test_steps_table_with_agent_id(mock_db_path: str) -> None:
    """Steps can be linked directly to an agent_id in the agents table."""
    db = Database(db_path=mock_db_path)
    await db.connect()

    session_id = await db.create_session("step-agent-session")
    aid = await db.create_agent(session_id=session_id, name="WorkerAgent", role="executor")

    step_id = await db.log_step(
        session_id=session_id,
        step_index=0,
        step_type="thought",
        agent_name="WorkerAgent",
        input_data="Start",
        output_data="Working",
        agent_id=aid,
    )
    assert step_id > 0

    steps = await db.get_steps(session_id)
    assert len(steps) == 1
    assert steps[0]["agent_id"] == aid

    await db.close()
