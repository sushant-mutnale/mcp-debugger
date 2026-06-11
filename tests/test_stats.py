import pytest
import asyncio
from typing import Any
from mcp_debugger.storage.database import Database
from mcp_debugger.analytics import (
    generate_sparkline,
    generate_bar_chart,
    aggregate_session_stats,
    compare_sessions_stats,
)


@pytest.fixture
def mock_db_path(tmp_path: Any) -> str:
    return str(tmp_path / "test_stats.db")


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
            "result": {"isError": True, "content": []}
        }
    )

    # Log an explicit error in database
    await db.log_error(
        session_id=session_id_a,
        message_id=None,
        error_type="protocol",
        error_message="Method not found",
        suggestion="Check name",
        error_code=-32601,
    )

    # Close session A
    await db.close_session(session_id_a, "completed")

    # Aggregate stats for session A
    stats_a = await aggregate_session_stats(db, session_id_a)
    assert stats_a.total_messages == 4  # 2 requests, 2 responses
    assert stats_a.client_to_server_count == 2
    assert stats_a.server_to_client_count == 2
    assert len(stats_a.top_tools) == 2

    # Check tools stats
    tools_dict = {t.name: t for t in stats_a.top_tools}
    assert "read_file" in tools_dict
    assert tools_dict["read_file"].calls == 1
    assert tools_dict["read_file"].error_rate == 0.0

    assert "write_file" in tools_dict
    assert tools_dict["write_file"].calls == 1
    assert tools_dict["write_file"].error_rate == 1.0
    assert tools_dict["write_file"].errors_count == 1

    assert stats_a.errors_by_category.get("protocol") == 1

    # Create session B to compare
    session_id_b = await db.create_session("server-b")
    # Log 1 message (only request)
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
    await db.close_session(session_id_b, "completed")

    stats_b = await aggregate_session_stats(db, session_id_b)

    # Compare
    comparison = compare_sessions_stats(stats_a, stats_b)
    assert comparison.session_id_a == session_id_a
    assert comparison.session_id_b == session_id_b
    assert comparison.messages_a == 4
    assert comparison.messages_b == 1
    assert comparison.messages_change_abs == -3

    # Check tool removal detection
    removed = comparison.removed_tools
    assert "write_file" in removed

    await db.close()
