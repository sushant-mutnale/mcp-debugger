"""Unit tests for SQLite attribution storage and query API."""

import pytest

from mcp_debugger.storage.database import Database


@pytest.mark.asyncio
async def test_log_and_get_attribution(mock_db_path: str) -> None:
    """Store and retrieve attribution record with structured details."""
    db = Database(db_path=mock_db_path)
    await db.connect()

    session_id = await db.create_session("agent-session")

    attr_id = await db.log_attribution(
        session_id=session_id,
        poc_step_index=2,
        failure_category="tool",
        root_cause_explanation="Empty result trap in fetch_records",
        mode="vcr",
        details={
            "ablation_results": [{"step_index": 2, "outcome_changed": True}],
            "poc_tool": "fetch_records",
        },
    )
    assert attr_id > 0

    record = await db.get_attribution(session_id)
    assert record is not None
    assert record["session_id"] == session_id
    assert record["poc_step_index"] == 2
    assert record["failure_category"] == "tool"
    assert record["root_cause_explanation"] == "Empty result trap in fetch_records"
    assert record["mode"] == "vcr"
    assert isinstance(record["details"], dict)
    assert record["details"]["poc_tool"] == "fetch_records"

    await db.close()


@pytest.mark.asyncio
async def test_attribution_cascade_delete(mock_db_path: str) -> None:
    """Attribution records cascade delete when session is deleted."""
    db = Database(db_path=mock_db_path)
    await db.connect()

    session_id = await db.create_session("temp-session")
    await db.log_attribution(
        session_id=session_id,
        poc_step_index=1,
        failure_category="agent",
        root_cause_explanation="Tool loop",
        mode="vcr",
    )

    # Verify present
    assert await db.get_attribution(session_id) is not None

    # Delete session
    conn = await db._get_conn()
    await conn.execute("PRAGMA foreign_keys = ON;")
    await conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    await conn.commit()

    # Verify cascaded deletion
    record = await db.get_attribution(session_id)
    assert record is None

    await db.close()


@pytest.mark.asyncio
async def test_multiple_attributions_vcr_and_live(mock_db_path: str) -> None:
    """Session can have multiple attribution comparisons (VCR vs live)."""
    db = Database(db_path=mock_db_path)
    await db.connect()

    session_id = await db.create_session("comparison-session")

    # VCR run
    id1 = await db.log_attribution(
        session_id=session_id,
        poc_step_index=1,
        failure_category="agent",
        root_cause_explanation="VCR loop detection",
        mode="vcr",
    )
    # Live run
    id2 = await db.log_attribution(
        session_id=session_id,
        poc_step_index=1,
        failure_category="agent",
        root_cause_explanation="Live counterfactual confirmation",
        mode="live",
    )

    assert id1 > 0
    assert id2 > id1

    # get_attribution returns latest (live)
    latest = await db.get_attribution(session_id)
    assert latest is not None
    assert latest["mode"] == "live"
    assert latest["root_cause_explanation"] == "Live counterfactual confirmation"

    # get_attributions returns both
    all_runs = await db.get_attributions(session_id)
    assert len(all_runs) == 2
    assert all_runs[0]["mode"] == "vcr"
    assert all_runs[1]["mode"] == "live"

    await db.close()
