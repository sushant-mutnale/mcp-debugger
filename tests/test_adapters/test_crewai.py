"""Unit tests for CrewAI multi-agent framework adapter."""

import asyncio
import json
import pytest

from mcp_debugger.adapters.crewai import CrewAITracker, trace_crewai
from mcp_debugger.sdk.ingestion import start_trace
from mcp_debugger.storage.database import Database


class MockCrewAIAgent:
    """Mock CrewAI Agent."""

    def __init__(self, role: str, goal: str = "", backstory: str = "") -> None:
        self.role = role
        self.goal = goal
        self.backstory = backstory


class MockCrew:
    """Mock CrewAI Crew."""

    def __init__(self, agents: list[MockCrewAIAgent], manager: MockCrewAIAgent | None = None) -> None:
        self.agents = agents
        self.manager_agent = manager

    def kickoff(self, inputs: dict[str, str] | None = None) -> dict[str, str]:
        return {"result": f"Completed task with inputs: {inputs}"}

    async def kickoff_async(self, inputs: dict[str, str] | None = None) -> dict[str, str]:
        await asyncio.sleep(0.01)
        return {"result": f"Async completed task with inputs: {inputs}"}


def test_crewai_tracker_agent_registration_and_handoff(mock_db_path: str) -> None:
    """CrewAITracker registers hierarchical agents and records handoffs."""
    with start_trace("crewai-test-session", db_path=mock_db_path) as session:
        tracker = CrewAITracker(session_id=session.session_id, db=session.db)

        # 1. Register agents
        mgr_id = tracker.register_agent(
            name="CrewManager",
            role="Project Manager",
            framework="crewai",
            metadata={"goal": "Coordinate project"},
        )
        assert mgr_id > 0

        worker_id = tracker.register_agent(
            name="ResearchAnalyst",
            role="Researcher",
            parent_agent_name="CrewManager",
            framework="crewai",
            metadata={"goal": "Gather facts"},
        )
        assert worker_id > mgr_id

        # 2. Record inter-agent delegation handoff
        tracker.on_task_handoff(
            from_agent="CrewManager",
            to_agent="ResearchAnalyst",
            task="Research MCP specs",
            context={"topic": "MCP 2026-07-28"},
        )

        # 3. Worker executes tool
        tracker.on_tool_call(
            agent_name="ResearchAnalyst",
            tool_name="web_search",
            tool_input={"query": "MCP protocol specs"},
            tool_output=json.dumps({"results": ["spec-2026.pdf"]}),
            latency_ms=12.5,
        )

        # 4. Worker finishes thought
        tracker.on_agent_thought(
            agent_name="ResearchAnalyst",
            thought="Summarizing results for manager.",
        )

    # Verify persisted data in database
    async def verify() -> None:
        db = Database(db_path=mock_db_path)
        await db.connect()

        # Check agents hierarchy
        tree = await db.get_agent_hierarchy(session.session_id)
        assert len(tree) == 1
        assert tree[0]["name"] == "CrewManager"
        assert len(tree[0]["children"]) == 1
        assert tree[0]["children"][0]["name"] == "ResearchAnalyst"

        # Check steps
        steps = await db.get_steps(session.session_id)
        assert len(steps) == 3

        # Handoff step
        assert steps[0]["step_type"] == "handoff"
        assert steps[0]["agent_name"] == "CrewManager"
        h_in = json.loads(steps[0]["input"])
        assert h_in["to_agent"] == "ResearchAnalyst"

        # Tool step
        assert steps[1]["step_type"] == "tool_call"
        assert steps[1]["agent_name"] == "ResearchAnalyst"

        # Thought step
        assert steps[2]["step_type"] == "thought"
        assert steps[2]["agent_name"] == "ResearchAnalyst"

        await db.close()

    asyncio.run(verify())


def test_trace_crewai_wrapper_sync(mock_db_path: str) -> None:
    """trace_crewai wraps crew.kickoff, registers agents, and captures run."""
    with start_trace("crew-wrapper-sync", db_path=mock_db_path) as session:
        manager = MockCrewAIAgent(role="Manager", goal="Direct team")
        worker = MockCrewAIAgent(role="Developer", goal="Write code")
        crew = MockCrew(agents=[worker], manager=manager)

        wrapped_crew = trace_crewai(crew)
        res = wrapped_crew.kickoff({"feature": "oauth"})
        assert "oauth" in res["result"]

    async def verify() -> None:
        db = Database(db_path=mock_db_path)
        await db.connect()
        agents = await db.get_agents(session.session_id)
        assert len(agents) == 2
        steps = await db.get_steps(session.session_id)
        assert len(steps) >= 1
        await db.close()

    asyncio.run(verify())


@pytest.mark.asyncio
async def test_trace_crewai_wrapper_async(mock_db_path: str) -> None:
    """trace_crewai wraps crew.kickoff_async, registers agents, and captures run."""
    async with start_trace("crew-wrapper-async", db_path=mock_db_path) as session:
        worker1 = MockCrewAIAgent(role="DataEngineer", goal="ETL")
        worker2 = MockCrewAIAgent(role="DataScientist", goal="Model")
        crew = MockCrew(agents=[worker1, worker2])

        wrapped_crew = trace_crewai(crew)
        res = await wrapped_crew.kickoff_async({"pipeline": "sales"})
        assert "sales" in res["result"]

    db = Database(db_path=mock_db_path)
    await db.connect()
    agents = await db.get_agents(session.session_id)
    assert len(agents) == 2
    await db.close()
