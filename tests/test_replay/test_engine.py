import asyncio
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict
import pytest

from mcp_debugger.storage.database import Database
from mcp_debugger.replay.engine import ReplayEngine, deep_compare
from mcp_debugger.replay.diff import DiffType


async def test_get_replay_messages(temp_db: Database) -> None:
    """Verify that get_replay_messages correctly constructs message history with matched responses."""
    session_id = await temp_db.create_session("dummy_cmd")

    # 1. Log a notification
    await temp_db.log_message(
        session_id=session_id,
        direction="client_to_server",
        message={"jsonrpc": "2.0", "method": "notifications/initialized"},
    )

    # 2. Log a request and its response
    await temp_db.log_message(
        session_id=session_id,
        direction="client_to_server",
        message={"jsonrpc": "2.0", "id": 100, "method": "ping", "params": {"value": "hello"}},
    )
    await temp_db.log_message(
        session_id=session_id,
        direction="server_to_client",
        message={"jsonrpc": "2.0", "id": 100, "result": {"value": "hello", "timestamp": "now"}},
    )

    # 3. Log a request with NO response
    await temp_db.log_message(
        session_id=session_id,
        direction="client_to_server",
        message={"jsonrpc": "2.0", "id": 101, "method": "tools/list"},
    )

    # Load messages
    messages = await temp_db.get_replay_messages(session_id)
    assert len(messages) == 3

    # Check notification
    assert messages[0]["message_type"] == "notification"
    assert messages[0]["method"] == "notifications/initialized"
    assert messages[0]["original_response"] is None

    # Check request with response
    assert messages[1]["message_type"] == "request"
    assert messages[1]["method"] == "ping"
    assert messages[1]["params"] == {"value": "hello"}
    assert messages[1]["original_response"] == {
        "jsonrpc": "2.0",
        "id": 100,
        "result": {"value": "hello", "timestamp": "now"},
    }

    # Check request with missing response
    assert messages[2]["message_type"] == "request"
    assert messages[2]["method"] == "tools/list"
    assert messages[2]["original_response"] is None


async def test_replay_engine_success(temp_db: Database) -> None:
    """Verify that replaying a session against a successful echo server works."""
    session_id = await temp_db.create_session("echo_cmd")

    # Request and response to be matched
    await temp_db.log_message(
        session_id=session_id,
        direction="client_to_server",
        message={"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {"status": "ok"}},
    )
    await temp_db.log_message(
        session_id=session_id,
        direction="server_to_client",
        message={"jsonrpc": "2.0", "id": 1, "result": {"status": "ok"}},
    )

    # Notification (no response)
    await temp_db.log_message(
        session_id=session_id,
        direction="client_to_server",
        message={"jsonrpc": "2.0", "method": "notifications/initialized"},
    )

    engine = ReplayEngine(temp_db)

    # Formulate echo command
    python_path = sys.executable
    echo_cmd = f'"{python_path}" tests/mock_servers/echo_server.py'

    result = await engine.replay(
        session_id=session_id,
        target_server_command=echo_cmd,
        timeout_ms=2000,
        persist=True,
    )

    assert result.total_messages_replayed == 2
    assert result.successful_responses == 1
    assert result.failed_responses == 0
    assert result.mismatched_responses == 0
    assert result.timed_out == 0

    # Notification check
    notification_msg = result.messages[1]
    assert notification_msg.method == "notifications/initialized"
    assert notification_msg.replayed_response is None
    assert notification_msg.matches is True

    # Request check
    request_msg = result.messages[0]
    assert request_msg.method == "ping"
    assert request_msg.replayed_response == {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"status": "ok"},
    }
    assert request_msg.matches is True


async def test_replay_engine_mismatch(temp_db: Database) -> None:
    """Verify that replaying a session with differing responses detects a mismatch and populates diffs."""
    session_id = await temp_db.create_session("echo_cmd")

    # Log request in database
    await temp_db.log_message(
        session_id=session_id,
        direction="client_to_server",
        message={"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {"status": "ok"}},
    )
    # Log differing response in database
    await temp_db.log_message(
        session_id=session_id,
        direction="server_to_client",
        message={"jsonrpc": "2.0", "id": 1, "result": {"status": "error"}},
    )

    engine = ReplayEngine(temp_db)

    python_path = sys.executable
    echo_cmd = f'"{python_path}" tests/mock_servers/echo_server.py'

    result = await engine.replay(
        session_id=session_id,
        target_server_command=echo_cmd,
        timeout_ms=2000,
        persist=True,
    )

    assert result.total_messages_replayed == 1
    assert result.successful_responses == 1
    assert result.mismatched_responses == 1

    msg = result.messages[0]
    assert msg.matches is False
    assert msg.diff is not None
    assert len(msg.diff) == 1
    assert msg.diff[0].type == DiffType.CHANGED
    assert msg.diff_text is not None
    assert "status" in msg.diff_text


async def test_replay_engine_timeout(temp_db: Database) -> None:
    """Verify that replaying against a hanging server triggers a timeout."""
    session_id = await temp_db.create_session("hang_cmd")

    await temp_db.log_message(
        session_id=session_id,
        direction="client_to_server",
        message={"jsonrpc": "2.0", "id": 1, "method": "ping"},
    )

    engine = ReplayEngine(temp_db)

    # Run against a command that sleeps indefinitely
    python_path = sys.executable
    sleep_cmd = f'"{python_path}" -c "import time; time.sleep(10)"'

    result = await engine.replay(
        session_id=session_id,
        target_server_command=sleep_cmd,
        timeout_ms=500,  # 0.5 seconds timeout
        persist=True,
    )

    assert result.total_messages_replayed == 1
    assert result.successful_responses == 0
    assert result.timed_out == 1
    assert result.messages[0].error == "Timeout waiting for response"


async def test_replay_integration_filesystem(temp_db: Database) -> None:
    """Integration test: record a session with filesystem server, then replay against it."""
    # Check if npx is installed
    npx_path = shutil.which("npx")
    if not npx_path:
        pytest.skip("npx not found, skipping filesystem integration test")

    with tempfile.TemporaryDirectory() as raw_tmpdir:
        tmpdir = str(Path(raw_tmpdir).resolve())
        server_cmd = f"npx -y @modelcontextprotocol/server-filesystem {tmpdir}"

        # Now start recording a session
        session_id = await temp_db.create_session(server_cmd)

        # Launch filesystem server to record
        process = await asyncio.create_subprocess_shell(
            server_cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        assert process.stdin and process.stdout
        setattr(process.stdout, "_limit", 10 * 1024 * 1024)

        # Wait for npx startup
        await asyncio.sleep(5.0)

        async def read_json_response(stdout: asyncio.StreamReader) -> Dict[str, Any]:
            for _ in range(100):  # limit loop to prevent infinite hang
                line_bytes = await stdout.readline()
                if not line_bytes:
                    raise EOFError("Connection closed before response received")
                line = line_bytes.decode("utf-8").strip()
                if not line:
                    continue
                try:
                    res = json.loads(line)
                    if isinstance(res, dict):
                        return res
                except json.JSONDecodeError:
                    continue
            raise RuntimeError("Exceeded non-JSON line limit")

        try:
            # 1. Initialize
            init_req = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "test-client", "version": "1.0"},
                },
            }
            await temp_db.log_message(session_id, "client_to_server", init_req)
            process.stdin.write((json.dumps(init_req) + "\n").encode("utf-8"))
            await process.stdin.drain()

            # Read response
            init_resp = await read_json_response(process.stdout)
            await temp_db.log_message(session_id, "server_to_client", init_resp)

            # 2. Send notifications/initialized
            init_notif = {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
                "params": {},
            }
            await temp_db.log_message(session_id, "client_to_server", init_notif)
            process.stdin.write((json.dumps(init_notif) + "\n").encode("utf-8"))
            await process.stdin.drain()

            # 3. List tools
            list_req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
            await temp_db.log_message(session_id, "client_to_server", list_req)
            process.stdin.write((json.dumps(list_req) + "\n").encode("utf-8"))
            await process.stdin.drain()

            # Read response
            list_resp = await read_json_response(process.stdout)
            await temp_db.log_message(session_id, "server_to_client", list_resp)

        finally:
            if process.stdin:
                try:
                    process.stdin.close()
                except Exception:
                    pass
            try:
                process.terminate()
                await asyncio.wait_for(process.wait(), timeout=3.0)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass

        # Now, replay this session using the ReplayEngine
        engine = ReplayEngine(temp_db)
        result = await engine.replay(
            session_id=session_id,
            target_server_command=server_cmd,
            timeout_ms=5000,
            persist=True,
        )

        assert result.total_messages_replayed == 3
        assert result.successful_responses == 2
        assert result.failed_responses == 0
        assert result.mismatched_responses == 0
        assert result.timed_out == 0

        # Verify all messages match
        assert result.messages[0].matches is True  # initialize
        assert result.messages[1].matches is True  # notifications/initialized
        assert result.messages[2].matches is True  # tools/list


async def test_replay_engine_edge_cases(temp_db: Database) -> None:
    """Verify various edge cases, deep comparison, server spawn failure, and cleanup issues."""
    from unittest.mock import MagicMock, patch

    engine = ReplayEngine(temp_db)

    # 1. deep_compare edge cases
    # dict keys mismatch
    assert deep_compare({"a": 1}, {"b": 2}) is False
    # list lengths mismatch
    assert deep_compare([1], [1, 2]) is False
    # list element mismatch
    assert deep_compare([1], [2]) is False

    # 2. Server fails to spawn (invalid command)
    session_id = await temp_db.create_session("invalid_spawn")
    await temp_db.log_message(
        session_id=session_id,
        direction="client_to_server",
        message={"jsonrpc": "2.0", "id": 1, "method": "ping"},
    )
    with patch("asyncio.create_subprocess_shell", side_effect=OSError("spawn failed")):
        result = await engine.replay(
            session_id=session_id,
            target_server_command="nonexistent_command_xyz_123_invalid",
            timeout_ms=500,
            persist=True,
        )
    assert result.total_messages_replayed == 1
    assert "Failed to start server: spawn failed" in result.messages[0].error

    # 3. Callbacks and selective filtering
    called_back = []

    def callback(curr, total):
        called_back.append((curr, total))

    session_id_2 = await temp_db.create_session("echo_cmd")
    await temp_db.log_message(
        session_id=session_id_2,
        direction="client_to_server",
        message={"jsonrpc": "2.0", "id": 1, "method": "ping"},
    )
    await temp_db.log_message(
        session_id=session_id_2,
        direction="server_to_client",
        message={"jsonrpc": "2.0", "id": 1, "result": "pong"},
    )
    await temp_db.log_message(
        session_id=session_id_2,
        direction="client_to_server",
        message={"jsonrpc": "2.0", "id": 2, "method": "other"},
    )
    await temp_db.log_message(
        session_id=session_id_2,
        direction="server_to_client",
        message={"jsonrpc": "2.0", "id": 2, "result": "pong"},
    )

    python_path = sys.executable
    echo_cmd = f'"{python_path}" tests/mock_servers/echo_server.py'

    result_selective = await engine.replay(
        session_id=session_id_2,
        target_server_command=echo_cmd,
        replay_mode="selective",
        message_filter=["ping"],
        on_message_replayed=callback,
        persist=False,
    )
    # "ping" is replayed, "other" is skipped
    assert result_selective.total_messages_replayed == 1
    assert len(called_back) == 1
    assert called_back[0] == (1, 1)

    # 4. Wait_for general exception during waiting for response
    original_wait_for = asyncio.wait_for

    async def mock_wait_for(fut, timeout=None):
        if not asyncio.iscoroutine(fut):
            raise RuntimeError("simulated wait error")
        return await original_wait_for(fut, timeout=timeout)

    with patch("asyncio.wait_for", side_effect=mock_wait_for):
        result_error = await engine.replay(
            session_id=session_id_2,
            target_server_command=echo_cmd,
            persist=False,
        )
        assert any("simulated wait error" in str(m.error) for m in result_error.messages)

    # 5. Process terminate/kill exception handling during cleanup
    class MockProcess:
        def __init__(self):
            self.stdin = MagicMock()
            self.stdout = asyncio.StreamReader()
            self.stderr = None

        def terminate(self):
            raise RuntimeError("Simulated terminate failure")

        def kill(self):
            raise RuntimeError("Simulated kill failure")

        async def wait(self):
            return 0

    proc = MockProcess()
    proc.stdout.feed_data(b'{"jsonrpc": "2.0", "id": 1, "result": "pong"}\n')
    proc.stdout.feed_eof()

    with patch("asyncio.create_subprocess_shell", return_value=proc):
        result_cleanup = await engine.replay(
            session_id=session_id_2,
            target_server_command="dummy_cmd",
            persist=False,
        )
        assert result_cleanup.total_messages_replayed > 0

    # 6. Non-integer msg_id conversion failure handling
    session_id_str = await temp_db.create_session("echo_cmd")
    await temp_db.log_message(
        session_id=session_id_str,
        direction="client_to_server",
        message={"jsonrpc": "2.0", "id": "msg-abc", "method": "ping", "params": "pong"},
    )
    await temp_db.log_message(
        session_id=session_id_str,
        direction="server_to_client",
        message={"jsonrpc": "2.0", "id": "msg-abc", "result": "pong"},
    )
    result_str = await engine.replay(
        session_id=session_id_str,
        target_server_command=echo_cmd,
        persist=False,
    )
    assert result_str.total_messages_replayed == 1
    assert result_str.messages[0].matches is True
