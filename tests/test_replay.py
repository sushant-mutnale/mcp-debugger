"""Unit tests for the Replay Engine."""

import asyncio
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, AsyncGenerator, Dict
import pytest

from mcp_debugger.storage.database import Database
from mcp_debugger.replay.engine import ReplayEngine, deep_compare
from mcp_debugger.replay.diff import compare_json, render_diff, DiffType



@pytest.fixture
async def temp_db() -> AsyncGenerator[Database, None]:
    """Fixture that returns a temporary database instance and closes it after the test."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = Database(db_path=path)
    await db.connect()
    yield db
    await db.close()
    try:
        os.remove(path)
    except Exception:
        pass


def test_deep_compare() -> None:
    """Verify deep comparison of JSON objects works, ignoring expected variant keys."""
    obj1 = {"status": "ok", "timestamp": 1234567, "data": {"val": 10, "latency_ms": 50}}
    obj2 = {"status": "ok", "timestamp": 7654321, "data": {"val": 10, "latency_ms": 20}}
    assert deep_compare(obj1, obj2)

    # Different value
    obj3 = {"status": "failed", "timestamp": 1234567, "data": {"val": 10}}
    assert not deep_compare(obj1, obj3)

    # Different nested value
    obj4 = {"status": "ok", "timestamp": 1234567, "data": {"val": 20}}
    assert not deep_compare(obj1, obj4)

    # Missing keys
    obj5 = {"status": "ok"}
    assert not deep_compare(obj1, obj5)


def test_diff() -> None:
    """Verify compare_json and render_diff on JSON structures."""
    # 1. Simple unchanged
    assert compare_json({"a": 1}, {"a": 1}) is None

    # 2. Simple changed
    diff = compare_json({"a": 1}, {"a": 2})
    assert diff is not None
    assert diff.type == DiffType.CHANGED
    assert len(diff.children) == 1
    assert diff.children[0].path == "a"
    assert diff.children[0].type == DiffType.CHANGED
    assert diff.children[0].old_value == 1
    assert diff.children[0].new_value == 2

    # 3. Added and Removed keys
    diff = compare_json({"a": 1, "b": 2}, {"b": 2, "c": 3})
    assert diff is not None
    assert len(diff.children) == 2
    paths = {c.path: c for c in diff.children}
    assert "a" in paths
    assert paths["a"].type == DiffType.REMOVED
    assert paths["a"].old_value == 1

    assert "c" in paths
    assert paths["c"].type == DiffType.ADDED
    assert paths["c"].new_value == 3

    # 4. Nested dict changed
    diff = compare_json({"meta": {"status": "ok"}}, {"meta": {"status": "error"}})
    assert diff is not None
    # Check hierarchy
    assert diff.children[0].path == "meta"
    assert diff.children[0].children[0].path == "meta.status"
    assert diff.children[0].children[0].type == DiffType.CHANGED
    assert diff.children[0].children[0].old_value == "ok"
    assert diff.children[0].children[0].new_value == "error"

    # 5. List index comparison
    diff = compare_json({"arr": [1, 2, 3]}, {"arr": [1, 5, 3, 4]})
    assert diff is not None
    # Changed index [1] and added index [3]
    arr_diff = diff.children[0]
    assert arr_diff.path == "arr"
    assert len(arr_diff.children) == 2
    assert arr_diff.children[0].path == "arr[1]"
    assert arr_diff.children[0].type == DiffType.CHANGED
    assert arr_diff.children[0].old_value == 2
    assert arr_diff.children[0].new_value == 5
    assert arr_diff.children[1].path == "arr[3]"
    assert arr_diff.children[1].type == DiffType.ADDED
    assert arr_diff.children[1].new_value == 4

    # 6. Type changes
    diff = compare_json({"val": 42}, {"val": "forty-two"})
    assert diff is not None
    assert diff.children[0].type == DiffType.CHANGED
    assert diff.children[0].old_value == 42
    assert diff.children[0].new_value == "forty-two"

    # 7. Render diff output containing Rich markup representation
    rendered = render_diff(diff)
    assert "[yellow]" in rendered
    assert "[red]- 42" in rendered
    assert "[green]+ \"forty-two\"" in rendered

    # 8. Performance test with 1MB JSON (hits guard)
    large_orig = {"data": [i for i in range(150000)]}
    large_rep = {"data": [i if i != 75000 else -1 for i in range(150000)]}

    import time
    start = time.perf_counter()
    large_diff = compare_json(large_orig, large_rep)
    elapsed = time.perf_counter() - start
    assert elapsed < 0.5
    assert large_diff is not None
    assert "[JSON too large to diff]" in str(large_diff.old_value)



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
