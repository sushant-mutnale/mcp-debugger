import json
import asyncio
import pathlib
from unittest.mock import AsyncMock, patch
from datetime import datetime, timezone
from typer.testing import CliRunner

from mcp_debugger.cli import app
from mcp_debugger.storage.database import Database


def test_replay_command(mock_db_path: str, tmp_path: pathlib.Path, runner: CliRunner) -> None:
    """Test that the replay CLI command parses options, calls the engine, outputs correctly, and exits with correct codes."""
    from mcp_debugger.replay.engine import ReplayResult, ReplayedMessage

    # Populate a session first so get_session does not fail
    async def create_session() -> None:
        db = Database(db_path=mock_db_path)
        await db.connect()
        await db.create_session("original-server-cmd", friendly_name="test-session")
        await db.close()

    asyncio.run(create_session())

    # We mock ReplayEngine.replay
    # Setup mock result
    mock_result = ReplayResult(
        replay_id=42,
        session_id=1,
        target_server_command="mock-target",
        started_at=datetime.now(timezone.utc),
        ended_at=datetime.now(timezone.utc),
        total_messages_replayed=2,
        successful_responses=2,
        failed_responses=0,
        mismatched_responses=0,
        timed_out=0,
        messages=[
            ReplayedMessage(
                original_message_id=1,
                method="initialize",
                request_sent={"id": 1, "method": "initialize"},
                original_response={"id": 1, "result": {"protocolVersion": "2024-11-05"}},
                replayed_response={"id": 1, "result": {"protocolVersion": "2024-11-05"}},
                latency_ms=1.2,
                matches=True,
            ),
            ReplayedMessage(
                original_message_id=2,
                method="tools/list",
                request_sent={"id": 2, "method": "tools/list"},
                original_response={"id": 2, "result": {"tools": []}},
                replayed_response={"id": 2, "result": {"tools": []}},
                latency_ms=2.5,
                matches=True,
            ),
        ],
    )

    with patch(
        "mcp_debugger.replay.engine.ReplayEngine.replay", new_callable=AsyncMock
    ) as mock_replay:
        mock_replay.return_value = mock_result

        # Test successful match exit code 0
        result = runner.invoke(app, ["replay", "1", "--server", "mock-target"])
        assert result.exit_code == 0
        assert "Successful matches: 2" in result.stdout
        assert "Mismatches: 0" in result.stdout

        # Test --no-diff and --verbose flags
        result_verbose = runner.invoke(app, ["replay", "1", "--server", "mock-target", "-v"])
        assert result_verbose.exit_code == 0
        assert "Message #1: initialize" in result_verbose.stdout

        # Test --json mode
        result_json = runner.invoke(app, ["replay", "1", "--server", "mock-target", "--json"])
        assert result_json.exit_code == 0
        data = json.loads(result_json.stdout)
        assert data["summary"]["matches"] == 2
        assert data["summary"]["mismatches"] == 0

        # Test --output file redirection
        out_file = tmp_path / "replay_out.txt"
        result_out = runner.invoke(
            app, ["replay", "1", "--server", "mock-target", "-o", str(out_file)]
        )
        assert result_out.exit_code == 0
        assert out_file.exists()
        file_content = out_file.read_text(encoding="utf-8")
        assert "Successful matches: 2" in file_content

    # Test mismatch exit code 1
    mock_mismatch_result = ReplayResult(
        replay_id=43,
        session_id=1,
        target_server_command="mock-target",
        started_at=datetime.now(timezone.utc),
        ended_at=datetime.now(timezone.utc),
        total_messages_replayed=1,
        successful_responses=1,
        failed_responses=0,
        mismatched_responses=1,
        timed_out=0,
        messages=[
            ReplayedMessage(
                original_message_id=1,
                method="tools/list",
                request_sent={"id": 1, "method": "tools/list"},
                original_response={"id": 1, "result": {"tools": []}},
                replayed_response={"id": 1, "result": {"tools": [{"name": "extra"}]}},
                latency_ms=1.2,
                matches=False,
                diff=[],
                diff_text="~ result.tools: added new elements",
            )
        ],
    )

    with patch(
        "mcp_debugger.replay.engine.ReplayEngine.replay", new_callable=AsyncMock
    ) as mock_replay:
        mock_replay.return_value = mock_mismatch_result
        result_mismatch = runner.invoke(app, ["replay", "1", "--server", "mock-target"])
        assert result_mismatch.exit_code == 1
        assert "Mismatches: 1" in result_mismatch.stdout
        assert "Differences:" in result_mismatch.stdout

    # Test server start failure exit code 2
    mock_fail_start_result = ReplayResult(
        replay_id=None,
        session_id=1,
        target_server_command="mock-target",
        started_at=datetime.now(timezone.utc),
        ended_at=datetime.now(timezone.utc),
        total_messages_replayed=1,
        successful_responses=0,
        failed_responses=1,
        mismatched_responses=0,
        timed_out=0,
        messages=[
            ReplayedMessage(
                original_message_id=1,
                method="initialize",
                request_sent={"id": 1, "method": "initialize"},
                original_response={"id": 1, "result": {}},
                replayed_response=None,
                error="Failed to start server: [WinError 2] The system cannot find the file specified",
                latency_ms=0.0,
                matches=False,
            )
        ],
    )

    with patch(
        "mcp_debugger.replay.engine.ReplayEngine.replay", new_callable=AsyncMock
    ) as mock_replay:
        mock_replay.return_value = mock_fail_start_result
        result_fail_start = runner.invoke(app, ["replay", "1", "--server", "nonexistent-server"])
        assert result_fail_start.exit_code == 2
        assert "Failed to start server" in result_fail_start.stdout

    # Test server timeout exit code 2
    mock_timeout_result = ReplayResult(
        replay_id=44,
        session_id=1,
        target_server_command="mock-target",
        started_at=datetime.now(timezone.utc),
        ended_at=datetime.now(timezone.utc),
        total_messages_replayed=1,
        successful_responses=0,
        failed_responses=0,
        mismatched_responses=0,
        timed_out=1,
        messages=[
            ReplayedMessage(
                original_message_id=1,
                method="tools/list",
                request_sent={"id": 1, "method": "tools/list"},
                original_response={"id": 1, "result": {}},
                replayed_response=None,
                error="Timeout waiting for response",
                latency_ms=5000.0,
                matches=False,
            )
        ],
    )

    with patch(
        "mcp_debugger.replay.engine.ReplayEngine.replay", new_callable=AsyncMock
    ) as mock_replay:
        mock_replay.return_value = mock_timeout_result
        result_timeout = runner.invoke(app, ["replay", "1", "--server", "mock-target"])
        assert result_timeout.exit_code == 2
        assert "timed out" in result_timeout.stdout.lower()
