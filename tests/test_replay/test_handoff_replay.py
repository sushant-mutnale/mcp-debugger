"""Unit tests for cassette-backed handoff replay engine."""

import json
import pytest

from mcp_debugger.replay.handoff import HandoffReplayEngine, HandoffReplayResult
from mcp_debugger.storage.database import Database


async def setup_multi_agent_session(mock_db_path: str) -> int:
    """Helper to populate an upstream -> handoff -> downstream trajectory."""
    db = Database(db_path=mock_db_path)
    await db.connect()

    session_id = await db.create_session("handoff-replay-session")
    aid_pm = await db.create_agent(session_id, name="PM", role="orchestrator")
    aid_dev = await db.create_agent(session_id, name="Dev", role="programmer", parent_agent_id=aid_pm)

    # Step 0: PM thought (upstream)
    await db.log_step(session_id, 0, "thought", "PM", "Plan feature", "Spec ready", agent_id=aid_pm)

    # Step 1: PM tool call (upstream)
    await db.log_step(
        session_id,
        1,
        "tool_call",
        "PM",
        json.dumps({"tool": "read_spec", "args": ["auth.md"]}),
        json.dumps({"spec": "OAuth2"}),
        agent_id=aid_pm,
    )

    # Step 2: Handoff from PM to Dev
    await db.log_step(
        session_id,
        2,
        "handoff",
        "PM",
        json.dumps({
            "from_agent": "PM",
            "to_agent": "Dev",
            "task": "Implement OAuth",
            "transferred_context": {"spec": "OAuth2", "deadline": "today"},
        }),
        json.dumps({
            "to_agent": "Dev",
            "output_context": {"status": "delegated"},
        }),
        agent_id=aid_pm,
    )

    # Step 3: Dev thought (downstream baseline)
    await db.log_step(session_id, 3, "thought", "Dev", "Implement logic", "Writing code", agent_id=aid_dev)

    # Step 4: Dev tool call (downstream baseline)
    await db.log_step(
        session_id,
        4,
        "tool_call",
        "Dev",
        json.dumps({"tool": "write_file", "args": ["auth.py"]}),
        json.dumps({"status": "written", "lines": 42}),
        agent_id=aid_dev,
    )

    await db.close()
    return session_id


@pytest.mark.asyncio
async def test_load_handoff_cassette(mock_db_path: str) -> None:
    """Verifies that upstream steps and downstream baseline are partitioned correctly."""
    session_id = await setup_multi_agent_session(mock_db_path)
    engine = HandoffReplayEngine(db_path=mock_db_path)

    handoff_step, upstream, downstream = await engine.load_handoff_cassette(session_id)
    assert handoff_step["step_index"] == 2
    assert handoff_step["step_type"] == "handoff"
    # Upstream has steps 0, 1, 2
    assert len(upstream) == 3
    # Downstream baseline has steps 3, 4
    assert len(downstream) == 2
    assert downstream[0]["step_index"] == 3


@pytest.mark.asyncio
async def test_replay_from_handoff_no_divergence(mock_db_path: str) -> None:
    """Downstream callable returning original output records no divergence."""
    session_id = await setup_multi_agent_session(mock_db_path)
    engine = HandoffReplayEngine(db_path=mock_db_path)

    def mock_dev_agent(ctx: dict[str, str]) -> dict[str, str]:
        assert ctx["spec"] == "OAuth2"
        return {"status": "written", "lines": 42}

    result = await engine.replay_from_handoff(
        session_id=session_id,
        downstream_agent_callable=mock_dev_agent,
    )

    assert isinstance(result, HandoffReplayResult)
    assert result.session_id == session_id
    assert result.from_agent == "PM"
    assert result.to_agent == "Dev"
    assert result.upstream_steps_count == 3
    assert result.upstream_cost_saved is True
    assert result.divergence_detected is False


@pytest.mark.asyncio
async def test_replay_from_handoff_with_divergence(mock_db_path: str) -> None:
    """Downstream callable returning modified output reports divergence."""
    session_id = await setup_multi_agent_session(mock_db_path)
    engine = HandoffReplayEngine(db_path=mock_db_path)

    async def mock_dev_modified(ctx: dict[str, str]) -> dict[str, str]:
        return {"status": "written", "lines": 99, "extra": "feature"}

    result = await engine.replay_from_handoff(
        session_id=session_id,
        downstream_agent_callable=mock_dev_modified,
    )

    assert result.divergence_detected is True
    assert result.diff is not None


@pytest.mark.asyncio
async def test_replay_from_handoff_with_context_override(mock_db_path: str) -> None:
    """Replay allows overriding initial context for counterfactual experimentation."""
    session_id = await setup_multi_agent_session(mock_db_path)
    engine = HandoffReplayEngine(db_path=mock_db_path)

    received_ctx = {}

    def mock_dev_override(ctx: dict[str, str]) -> dict[str, str]:
        nonlocal received_ctx
        received_ctx = ctx
        return {"status": "ok"}

    patched_context = {"spec": "PKCE-OAuth2", "security_level": "high"}
    await engine.replay_from_handoff(
        session_id=session_id,
        downstream_agent_callable=mock_dev_override,
        override_context=patched_context,
    )

    assert received_ctx == patched_context
