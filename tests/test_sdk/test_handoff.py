"""Unit tests for inter-agent handoff tracking and context diff capture."""

import asyncio
import json
import pytest

from mcp_debugger.sdk.context import get_current_agent
from mcp_debugger.sdk.handoff import (
    calculate_context_diff,
    trace_handoff,
    trace_handoff_context,
)
from mcp_debugger.sdk.ingestion import start_trace
from mcp_debugger.storage.database import Database


def test_calculate_context_diff() -> None:
    """Calculates added, removed, and modified keys between contexts."""
    initial = {"status": "init", "user_id": 100, "shared_data": "v1"}
    updated = {"status": "in_progress", "user_id": 100, "task": "refactor"}

    diff = calculate_context_diff(initial, updated)
    assert diff["added"] == {"task": "refactor"}
    assert diff["removed"] == ["shared_data"]
    assert diff["modified"] == {
        "status": {"old": "init", "new": "in_progress"}
    }


def test_trace_handoff_decorator_sync(mock_db_path: str) -> None:
    """Synchronous function wrapped with @trace_handoff logs handoff step and transitions agent."""
    with start_trace("handoff-sync-session", db_path=mock_db_path) as session:

        @trace_handoff(from_agent="Orchestrator", to_agent="Worker", task="Process data")
        def delegate_work(context: dict[str, str]) -> dict[str, str]:
            assert get_current_agent() == "Worker"
            return {"status": "processed", "result": "ok"}

        res = delegate_work({"status": "pending"})
        assert res["status"] == "processed"

    # Verify database steps
    async def verify() -> None:
        db = Database(db_path=mock_db_path)
        await db.connect()
        steps = await db.get_steps(session.session_id)
        await db.close()

        assert len(steps) >= 1
        handoff_step = next(s for s in steps if s["step_type"] == "handoff")
        assert handoff_step["agent_name"] == "Orchestrator"

        input_data = json.loads(handoff_step["input"])
        assert input_data["from_agent"] == "Orchestrator"
        assert input_data["to_agent"] == "Worker"
        assert input_data["task"] == "Process data"

        output_data = json.loads(handoff_step["output"])
        assert output_data["to_agent"] == "Worker"
        assert "context_diff" in output_data

    asyncio.run(verify())


@pytest.mark.asyncio
async def test_trace_handoff_decorator_async(mock_db_path: str) -> None:
    """Async function wrapped with @trace_handoff logs handoff step and transitions agent."""
    async with start_trace("handoff-async-session", db_path=mock_db_path) as session:

        @trace_handoff(from_agent="Manager", to_agent="Researcher", task="Web search")
        async def async_delegate(query: str) -> dict[str, str]:
            assert get_current_agent() == "Researcher"
            await asyncio.sleep(0.01)
            return {"findings": f"Found results for {query}"}

        res = await async_delegate("MCP 2026 specs")
        assert "Found results" in res["findings"]

    db = Database(db_path=mock_db_path)
    await db.connect()
    steps = await db.get_steps(session.session_id)
    await db.close()

    handoff_step = next(s for s in steps if s["step_type"] == "handoff")
    assert handoff_step["agent_name"] == "Manager"
    input_data = json.loads(handoff_step["input"])
    assert input_data["to_agent"] == "Researcher"


def test_trace_handoff_context_manager(mock_db_path: str) -> None:
    """trace_handoff_context manager records handoff with explicit state diffs."""
    with start_trace("handoff-ctx-session", db_path=mock_db_path) as session:
        initial_ctx = {"step": 1, "state": "draft"}
        with trace_handoff_context(
            from_agent="Planner",
            to_agent="Executor",
            task="Execute plan",
            initial_context=initial_ctx,
        ) as h:
            assert get_current_agent() == "Executor"
            h.set_output_context({"step": 2, "state": "completed", "artifacts": ["file.txt"]})

    async def verify() -> None:
        db = Database(db_path=mock_db_path)
        await db.connect()
        steps = await db.get_steps(session.session_id)
        await db.close()

        handoff_step = next(s for s in steps if s["step_type"] == "handoff")
        out = json.loads(handoff_step["output"])
        diff = out["context_diff"]
        assert diff["added"] == {"artifacts": ["file.txt"]}
        assert diff["modified"] == {"step": {"old": 1, "new": 2}, "state": {"old": "draft", "new": "completed"}}

    asyncio.run(verify())
