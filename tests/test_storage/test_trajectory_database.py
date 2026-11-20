import os
import tempfile
import pytest
import aiosqlite

from mcp_debugger.storage.database import Database


@pytest.fixture
async def temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = Database(db_path=path)
    await db.connect()
    yield db
    await db.close()
    if os.path.exists(path):
        os.remove(path)


@pytest.mark.asyncio
async def test_steps_table_schema(temp_db: Database) -> None:
    """Verify that steps table exists with all required columns and constraints."""
    conn = await temp_db._get_conn()
    async with conn.execute("PRAGMA table_info(steps);") as cursor:
        columns = {row[1]: row[2] for row in await cursor.fetchall()}

    expected_columns = [
        "id",
        "session_id",
        "step_index",
        "step_type",
        "agent_name",
        "input",
        "output",
        "content_hash",
        "tokens_input",
        "tokens_output",
        "latency_ms",
        "created_at",
    ]
    for col in expected_columns:
        assert col in columns, f"Missing column {col} in steps table"

    # Test CHECK constraint on step_type
    sid = await temp_db.create_session("test-server")
    with pytest.raises(aiosqlite.IntegrityError):
        await conn.execute(
            """
            INSERT INTO steps (session_id, step_index, step_type, input)
            VALUES (?, ?, ?, ?)
            """,
            (sid, 0, "invalid_type", "some input"),
        )
        await conn.commit()


@pytest.mark.asyncio
async def test_log_step_and_get_steps(temp_db: Database) -> None:
    """Verify logging steps and querying them ordered by step_index."""
    sid = await temp_db.create_session("test-server", friendly_name="agent-run")

    step_id_0 = await temp_db.log_step(
        session_id=sid,
        step_index=0,
        step_type="thought",
        agent_name="planner",
        input_data="Analyze user request",
        output_data="Created sub-tasks",
        tokens_input=100,
        tokens_output=25,
        latency_ms=45.0,
    )
    assert step_id_0 > 0

    step_id_1 = await temp_db.log_step(
        session_id=sid,
        step_index=1,
        step_type="tool_call",
        agent_name="worker",
        input_data='{"command": "search"}',
        output_data='{"results": 5}',
        tokens_input=150,
        tokens_output=50,
        latency_ms=120.5,
    )
    assert step_id_1 > step_id_0

    step_id_2 = await temp_db.log_step(
        session_id=sid,
        step_index=2,
        step_type="handoff",
        agent_name="worker",
        input_data="Hand off to reviewer",
        output_data="Reviewer accepted",
    )
    assert step_id_2 > step_id_1

    steps = await temp_db.get_steps(sid)
    assert len(steps) == 3
    assert steps[0]["step_index"] == 0
    assert steps[0]["step_type"] == "thought"
    assert steps[0]["agent_name"] == "planner"
    assert steps[0]["tokens_input"] == 100
    assert len(steps[0]["content_hash"]) == 64

    assert steps[1]["step_index"] == 1
    assert steps[1]["step_type"] == "tool_call"
    assert steps[1]["agent_name"] == "worker"
    assert steps[1]["latency_ms"] == 120.5

    assert steps[2]["step_index"] == 2
    assert steps[2]["step_type"] == "handoff"


@pytest.mark.asyncio
async def test_content_hash_deduplication(temp_db: Database) -> None:
    """Verify that logging duplicate identical steps reuses existing step record."""
    sid = await temp_db.create_session("test-server")

    id1 = await temp_db.log_step(
        session_id=sid,
        step_index=0,
        step_type="thought",
        agent_name="agent-a",
        input_data="Thinking about problem",
        output_data="Thought result 1",
    )

    # Attempt to log identical step (same session, agent, step_type, input)
    id2 = await temp_db.log_step(
        session_id=sid,
        step_index=1,
        step_type="thought",
        agent_name="agent-a",
        input_data="Thinking about problem",
        output_data="Thought result 1",
        deduplicate=True,
    )

    assert id1 == id2
    steps = await temp_db.get_steps(sid)
    assert len(steps) == 1


@pytest.mark.asyncio
async def test_cascade_deletion(temp_db: Database) -> None:
    """Verify that deleting a session cascades and deletes associated trajectory steps."""
    sid = await temp_db.create_session("test-server")
    await temp_db.log_step(
        session_id=sid,
        step_index=0,
        step_type="llm_call",
        agent_name="agent-b",
        input_data="Generate code",
        output_data="def foo(): pass",
    )

    steps_before = await temp_db.get_steps(sid)
    assert len(steps_before) == 1

    await temp_db.delete_session(sid)
    steps_after = await temp_db.get_steps(sid)
    assert len(steps_after) == 0
