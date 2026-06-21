import json
import asyncio
import pytest
from typer.testing import CliRunner

from mcp_debugger.cli import app
from mcp_debugger.storage.database import Database
from mcp_debugger.analytics import (
    generate_sparkline,
    generate_bar_chart,
    aggregate_session_stats,
    compare_sessions_stats,
)


def test_generate_sparkline() -> None:
    # Empty
    assert generate_sparkline([]) == ""

    # Single value
    assert generate_sparkline([10.0]) == "▄"

    # All zeros
    assert generate_sparkline([0.0, 0.0, 0.0], width=3) == "   "

    # All identical non-zero values
    assert generate_sparkline([12.5, 12.5, 12.5], width=3) == "▄▄▄"

    # Scaling values
    spark = generate_sparkline([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0], width=8)
    assert len(spark) == 8
    # Min is mapped to lowest block, max to highest
    assert spark[0] == " "
    assert spark[-1] == "█"

    # Downsampling
    large_list = list(range(100))
    spark_sampled = generate_sparkline([float(x) for x in large_list], width=10)
    assert len(spark_sampled) == 10


def test_generate_bar_chart() -> None:
    # Empty
    assert generate_bar_chart({}) == []

    # Normal distribution
    counts = {"tools/call": 8, "initialize": 2}
    chart = generate_bar_chart(counts, max_width=10)
    assert len(chart) == 2
    # Sorted by count
    assert chart[0][0] == "tools/call"
    assert chart[0][1] == 8
    assert chart[0][2] == 0.8
    assert chart[0][3] == "████████░░"

    assert chart[1][0] == "initialize"
    assert chart[1][1] == 2
    assert chart[1][2] == 0.2
    assert chart[1][3] == "██░░░░░░░░"


@pytest.mark.asyncio
async def test_aggregate_and_compare_stats(mock_db_path: str) -> None:
    db = Database(db_path=mock_db_path)
    await db.connect()

    # Create session A
    session_id_a = await db.create_session("server-a")

    # Log message: request
    await db.log_message(
        session_id=session_id_a,
        direction="client_to_server",
        message={
            "jsonrpc": "2.0",
            "id": "1",
            "method": "tools/call",
            "params": {"name": "read_file"}
        }
    )
    # Simulate a delay by hand and log response with latency
    await asyncio.sleep(0.01)
    await db.log_message(
        session_id=session_id_a,
        direction="server_to_client",
        message={
            "jsonrpc": "2.0",
            "id": "1",
            "result": {"content": [{"type": "text", "text": "hello"}]}
        }
    )

    # Log tool calls and execution failures
    await db.log_message(
        session_id=session_id_a,
        direction="client_to_server",
        message={
            "jsonrpc": "2.0",
            "id": "2",
            "method": "tools/call",
            "params": {"name": "write_file"}
        }
    )
    await db.log_message(
        session_id=session_id_a,
        direction="server_to_client",
        message={
            "jsonrpc": "2.0",
            "id": "2",
            "result": {"isError": True, "content": [{"type": "text", "text": "Error write"}]}
        }
    )

    # Log an error to test categorization
    await db.log_error(
        session_id=session_id_a,
        message_id=None,
        error_type="protocol",
        error_message="Method not found",
        suggestion="check",
        error_code=-32601
    )
    await db.log_error(
        session_id=session_id_a,
        message_id=None,
        error_type="tool_execution",
        error_message="Tool failed",
        suggestion="fix it",
        error_code=None
    )

    # Now aggregate
    stats_a = await aggregate_session_stats(db, session_id_a)
    assert stats_a.session_id == session_id_a
    assert stats_a.total_messages == 4
    assert stats_a.client_to_server_count == 2
    assert stats_a.server_to_client_count == 2
    assert any(t.name == "read_file" for t in stats_a.top_tools)
    assert any(t.name == "write_file" for t in stats_a.top_tools)
    assert stats_a.errors_by_category["protocol"] == 1
    assert stats_a.errors_by_category["tool_execution"] == 1

    # Create session B
    session_id_b = await db.create_session("server-b")
    await db.log_message(
        session_id=session_id_b,
        direction="client_to_server",
        message={
            "jsonrpc": "2.0",
            "id": "1",
            "method": "tools/call",
            "params": {"name": "read_file"}
        }
    )
    await db.log_message(
        session_id=session_id_b,
        direction="server_to_client",
        message={
            "jsonrpc": "2.0",
            "id": "1",
            "result": {"content": [{"type": "text", "text": "hello B"}]}
        }
    )

    stats_b = await aggregate_session_stats(db, session_id_b)
    comparison = compare_sessions_stats(stats_a, stats_b)

    assert comparison.session_id_a == session_id_a
    assert comparison.session_id_b == session_id_b
    assert comparison.messages_change_abs == -2  # 2 vs 4
    assert any(tc.name == "read_file" for tc in comparison.tool_changes)
    assert "write_file" in comparison.removed_tools

    await db.close()


def test_stats_command(mock_db_path: str, runner: CliRunner) -> None:
    """Verify stats command runs and aggregates statistics."""
    async def populate() -> None:
        db = Database(db_path=mock_db_path)
        await db.connect()
        session_id = await db.create_session("my-session")

        # Log tools/call request
        await db.log_message(
            session_id=session_id,
            direction="client_to_server",
            message={
                "jsonrpc": "2.0",
                "id": "1",
                "method": "tools/call",
                "params": {"name": "hello_tool"}
            }
        )
        # Log response
        await db.log_message(
            session_id=session_id,
            direction="server_to_client",
            message={
                "jsonrpc": "2.0",
                "id": "1",
                "result": {"isError": True, "content": []}
            }
        )

        # Log an error
        await db.log_error(
            session_id=session_id,
            message_id=None,
            error_type="protocol",
            error_message="Fail",
            suggestion="Fix it",
            error_code=-1,
        )

        await db.close()

    asyncio.run(populate())

    # Regular stats output
    result = runner.invoke(app, ["stats", "1"])
    assert result.exit_code == 0
    assert "Session #1" in result.stdout
    assert "Top Tools" in result.stdout
    assert "hello_tool" in result.stdout
    assert "Errors by Category" in result.stdout
    assert "Method Distribution" in result.stdout
    assert "Error Trend" in result.stdout

    # JSON mode
    result_json = runner.invoke(app, ["stats", "1", "--json"])
    assert result_json.exit_code == 0
    parsed = json.loads(result_json.stdout)
    assert parsed["session_id"] == 1
    assert parsed["errors_by_category"]["protocol"] == 1

    # File output modes (Markdown and JSON)
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Markdown output
        out_file = Path(tmp_dir) / "report.md"
        result_md = runner.invoke(app, ["stats", "1", "--output", str(out_file)])
        assert result_md.exit_code == 0
        assert out_file.exists()
        md_content = out_file.read_text(encoding="utf-8")
        assert "Session Statistics Report" in md_content

        # JSON output (by naming file .json)
        out_json = Path(tmp_dir) / "report.json"
        result_json_out = runner.invoke(app, ["stats", "1", "--output", str(out_json)])
        assert result_json_out.exit_code == 0
        assert out_json.exists()
        json_content = out_json.read_text(encoding="utf-8")
        parsed_out = json.loads(json_content)
        assert parsed_out["session_id"] == 1


def test_compare_command(mock_db_path: str, runner: CliRunner) -> None:
    """Verify compare command runs and calculates session differences."""
    async def populate() -> None:
        db = Database(db_path=mock_db_path)
        await db.connect()

        # Session A
        session_a = await db.create_session("sess-a")
        await db.log_message(
            session_id=session_a,
            direction="client_to_server",
            message={"jsonrpc": "2.0", "id": "1", "method": "tools/call", "params": {"name": "tool-a"}}
        )
        await db.close_session(session_a, "completed")

        # Session B
        session_b = await db.create_session("sess-b")
        await db.log_message(
            session_id=session_b,
            direction="client_to_server",
            message={"jsonrpc": "2.0", "id": "1", "method": "tools/call", "params": {"name": "tool-b"}}
        )
        await db.close_session(session_b, "completed")

        await db.close()

    asyncio.run(populate())

    result = runner.invoke(app, ["compare", "1", "2"])
    assert result.exit_code == 0
    assert "Comparing session #1 (old) vs #2 (new)" in result.stdout
    assert "Tool Call Changes" in result.stdout
    assert "tool-a" in result.stdout
    assert "tool-b" in result.stdout

    # JSON mode
    result_json = runner.invoke(app, ["compare", "1", "2", "--json"])
    assert result_json.exit_code == 0
    parsed = json.loads(result_json.stdout)
    assert parsed["session_id_a"] == 1
    assert parsed["session_id_b"] == 2


@pytest.mark.asyncio
async def test_analytics_edge_cases(mock_db_path: str) -> None:
    db = Database(db_path=mock_db_path)
    await db.connect()

    # 1. aggregate_session_stats raises ValueError for missing session
    with pytest.raises(ValueError, match="Session 999 not found"):
        await aggregate_session_stats(db, 999)

    # 2. Session with invalid started_at format
    session_id = await db.create_session("sess-edge")
    # Manually update started_at to invalid format
    conn = await db._get_conn()
    await conn.execute(
        "UPDATE sessions SET started_at = 'invalid-date' WHERE id = ?",
        (session_id,)
    )
    await conn.commit()

    # Log messages via manual SQL to bypass valid serialization or trigger specific catch blocks
    # 1. Invalid JSON params request (already maps to 'unknown')
    await conn.execute(
        """
        INSERT INTO messages (session_id, message_id, direction, message_type, method, params, timestamp)
        VALUES (?, '1', 'client_to_server', 'request', 'tools/call', '{invalid-json}', 123456.7)
        """,
        (session_id,)
    )
    # 2. Match request/response with error string
    await conn.execute(
        """
        INSERT INTO messages (session_id, message_id, direction, message_type, method, params, timestamp)
        VALUES (?, '10', 'client_to_server', 'request', 'tools/call', '{"name": "tool_err"}', 123456.7)
        """,
        (session_id,)
    )
    await conn.execute(
        """
        INSERT INTO messages (session_id, message_id, direction, message_type, error, timestamp)
        VALUES (?, '10', 'server_to_client', 'response', '{"code": -32000, "message": "fail"}', 123456.7)
        """,
        (session_id,)
    )
    # 3. Match request/response with invalid JSON result string
    await conn.execute(
        """
        INSERT INTO messages (session_id, message_id, direction, message_type, method, params, timestamp)
        VALUES (?, '11', 'client_to_server', 'request', 'tools/call', '{"name": "tool_invalid_res"}', 123456.7)
        """,
        (session_id,)
    )
    await conn.execute(
        """
        INSERT INTO messages (session_id, message_id, direction, message_type, result, timestamp)
        VALUES (?, '11', 'server_to_client', 'response', '{invalid-json}', 123456.7)
        """,
        (session_id,)
    )
    # 4. Match request/response with valid json isError=True result
    await conn.execute(
        """
        INSERT INTO messages (session_id, message_id, direction, message_type, method, params, timestamp)
        VALUES (?, '12', 'client_to_server', 'request', 'tools/call', '{"name": "tool_ok"}', 123456.7)
        """,
        (session_id,)
    )
    await conn.execute(
        """
        INSERT INTO messages (session_id, message_id, direction, message_type, result, timestamp)
        VALUES (?, '12', 'server_to_client', 'response', '{"isError": true}', 123456.7)
        """,
        (session_id,)
    )

    await conn.commit()

    stats = await aggregate_session_stats(db, session_id)
    assert stats.duration_seconds is None  # invalid date format handled gracefully
    # Tool call with invalid json is mapped to 'unknown'
    assert any(t.name == "unknown" for t in stats.top_tools)

    # 3. Trigger execution failure fallback (line 247-249)
    from unittest.mock import patch
    original_execute = conn.execute

    def mock_execute(sql, *args, **kwargs):
        if "tools/call" in sql:
            raise RuntimeError("Query failed")
        return original_execute(sql, *args, **kwargs)

    with patch.object(conn, "execute", side_effect=mock_execute):
        # Should not raise exception
        stats_fallback = await aggregate_session_stats(db, session_id)
        assert stats_fallback.top_tools == []

    await db.close()


def test_compare_sessions_stats_edge_cases() -> None:
    from mcp_debugger.analytics import SessionStats, ToolMetric, compare_sessions_stats

    # Session A stats
    stats_a = SessionStats(
        session_id=1,
        friendly_name="sess-a",
        server_command="cmd",
        started_at="2026-06-20 12:00:00",
        ended_at="2026-06-20 12:05:00",
        status="completed",
        duration_seconds=300,  # 300 seconds
        total_messages=10,
        client_to_server_count=5,
        server_to_client_count=5,
        top_tools=[
            ToolMetric(name="tool_inc_dec", calls=5, avg_latency_ms=100.0, errors_count=0, error_rate=0.0),
            ToolMetric(name="tool_removed", calls=2, avg_latency_ms=50.0, errors_count=0, error_rate=0.0)
        ],
        errors_by_category={"protocol": 1},
        latency_min=10.0,
        latency_max=200.0,
        latency_avg=100.0,
        latency_trend=[100.0] * 5,
        method_distribution={"tools/call": 5},
        error_trend=[0] * 5
    )

    # Session B stats:
    # 1. duration is faster (200 seconds -> line 325)
    # 2. tool_inc_dec calls decreased to 3 (line 384)
    # 3. tool_new added (line 364)
    # 4. regression in error rate (errors_by_category has 5 errors -> regression -> line 415)
    stats_b1 = SessionStats(
        session_id=2,
        friendly_name="sess-b1",
        server_command="cmd",
        started_at="2026-06-20 12:00:00",
        ended_at="2026-06-20 12:03:20",
        status="completed",
        duration_seconds=200,
        total_messages=10,
        client_to_server_count=5,
        server_to_client_count=5,
        top_tools=[
            ToolMetric(name="tool_inc_dec", calls=3, avg_latency_ms=120.0, errors_count=0, error_rate=0.0),
            ToolMetric(name="tool_new", calls=4, avg_latency_ms=80.0, errors_count=0, error_rate=0.0)
        ],
        errors_by_category={"protocol": 5},
        latency_min=10.0,
        latency_max=200.0,
        latency_avg=100.0,
        latency_trend=[100.0] * 5,
        method_distribution={"tools/call": 5},
        error_trend=[0] * 5
    )

    comp1 = compare_sessions_stats(stats_a, stats_b1)
    assert "faster" in comp1.duration_change_str
    assert "regression" in comp1.error_rate_change_str
    # find tool_inc_dec change
    change_inc_dec = next(t for t in comp1.tool_changes if t.name == "tool_inc_dec")
    assert "↓" in change_inc_dec.change_str

    # Session B2 stats:
    # 1. duration is slower (400 seconds -> line 327)
    # 2. tool_inc_dec calls increased to 8 (line 382)
    stats_b2 = SessionStats(
        session_id=3,
        friendly_name="sess-b2",
        server_command="cmd",
        started_at="2026-06-20 12:00:00",
        ended_at="2026-06-20 12:06:40",
        status="completed",
        duration_seconds=400,
        total_messages=10,
        client_to_server_count=5,
        server_to_client_count=5,
        top_tools=[
            ToolMetric(name="tool_inc_dec", calls=8, avg_latency_ms=120.0, errors_count=0, error_rate=0.0)
        ],
        errors_by_category={"protocol": 0},
        latency_min=10.0,
        latency_max=200.0,
        latency_avg=100.0,
        latency_trend=[100.0] * 5,
        method_distribution={"tools/call": 5},
        error_trend=[0] * 5
    )

    comp2 = compare_sessions_stats(stats_a, stats_b2)
    assert "slower" in comp2.duration_change_str
    change_inc_dec2 = next(t for t in comp2.tool_changes if t.name == "tool_inc_dec")
    assert "↑" in change_inc_dec2.change_str

    # Session B3: duration no change (300 seconds)
    stats_b3 = SessionStats(
        session_id=4,
        friendly_name="sess-b3",
        server_command="cmd",
        started_at="2026-06-20 12:00:00",
        ended_at="2026-06-20 12:05:00",
        status="completed",
        duration_seconds=300,
        total_messages=10,
        client_to_server_count=5,
        server_to_client_count=5,
        top_tools=[
            ToolMetric(name="tool_inc_dec", calls=5, avg_latency_ms=100.0, errors_count=0, error_rate=0.0)
        ],
        errors_by_category={"protocol": 1},
        latency_min=10.0,
        latency_max=200.0,
        latency_avg=100.0,
        latency_trend=[100.0] * 5,
        method_distribution={"tools/call": 5},
        error_trend=[0] * 5
    )
    comp3 = compare_sessions_stats(stats_a, stats_b3)
    assert comp3.duration_change_str == "no change"

