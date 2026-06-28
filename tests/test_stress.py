import asyncio
import json
import os
import sys
import time
from pathlib import Path
import pytest

from mcp_debugger.storage.database import Database
from mcp_debugger.replay.engine import ReplayEngine


@pytest.mark.asyncio
async def test_database_insertion_stress(tmp_path: Path) -> None:
    """Stress test: Log 5,000 messages and measure insertion speed."""
    db_path = tmp_path / "stress_insert.db"
    db = Database(str(db_path))
    await db.connect()

    session_id = await db.create_session("stress_command")
    assert session_id != -1

    # Enable background batching
    db.start_flush_task()

    num_messages = 5000
    print(f"\n[STRESS] Logging {num_messages} messages...")
    start_time = time.perf_counter()

    for i in range(num_messages):
        # alternate requests/responses
        if i % 2 == 0:
            msg = {"jsonrpc": "2.0", "id": i, "method": "test/method", "params": {"index": i}}
            direction = "client_to_server"
        else:
            msg = {"jsonrpc": "2.0", "id": i - 1, "result": {"index": i - 1, "status": "ok"}}
            direction = "server_to_client"

        await db.log_message(session_id=session_id, direction=direction, message=msg)

    # Flush and wait for queue to drain
    await db.stop_flush_task()
    end_time = time.perf_counter()
    duration = end_time - start_time

    print(f"[STRESS] Inserted {num_messages} messages in {duration:.4f} seconds.")
    # Check that database contains all messages
    messages = await db.get_messages(session_id)
    assert len(messages) == num_messages

    # Assert performance threshold: 5,000 messages in < 20 seconds (relaxed for coverage overhead)
    assert duration < 20.0
    await db.close()


@pytest.mark.asyncio
async def test_replay_stress(tmp_path: Path) -> None:
    """Stress test: Replay 1,000 messages and measure performance."""
    db_path = tmp_path / "stress_replay.db"
    db = Database(str(db_path))
    await db.connect()

    session_id = await db.create_session("stress_replay")

    # Log 1,000 messages (500 requests, 500 responses)
    for i in range(500):
        await db.log_message(
            session_id=session_id,
            direction="client_to_server",
            message={"jsonrpc": "2.0", "id": i, "method": "ping", "params": {"val": i}},
        )
        await db.log_message(
            session_id=session_id,
            direction="server_to_client",
            message={"jsonrpc": "2.0", "id": i, "result": {"val": i}},
        )

    engine = ReplayEngine(db)
    python_path = sys.executable
    echo_cmd = f'"{python_path}" tests/mock_servers/echo_server.py'

    start_time = time.perf_counter()
    replay_result = await engine.replay(session_id, target_server_command=echo_cmd)
    end_time = time.perf_counter()
    duration = end_time - start_time

    print(f"\n[STRESS] Replayed 1,000 messages in {duration:.4f} seconds.")
    assert replay_result.successful_responses == 500
    assert replay_result.mismatched_responses == 0
    # Replay of 1,000 messages should easily run in < 30 seconds (relaxed for coverage overhead)
    assert duration < 30.0

    await db.close()


@pytest.mark.asyncio
async def test_concurrent_proxies_stress(tmp_path: Path) -> None:
    """Stress test: Run two proxies simultaneously pointing to the same SQLite DB."""
    db_path = tmp_path / "concurrent_stress.db"
    mock_server_path = tmp_path / "mock_echo_server.py"

    mock_server_code = """
import sys
import json

while True:
    line = sys.stdin.readline()
    if not line:
        break
    if not line.strip():
        continue
    try:
        msg = json.loads(line)
        if "id" in msg:
            resp = {"jsonrpc": "2.0", "id": msg["id"], "result": msg.get("params")}
            sys.stdout.write(json.dumps(resp) + "\\n")
            sys.stdout.flush()
    except Exception:
        pass
"""
    mock_server_path.write_text(mock_server_code, encoding="utf-8")

    test_env = os.environ.copy()
    test_env["MCP_DEBUGGER_DATABASE_PATH"] = str(db_path)
    test_env["PYTHONIOENCODING"] = "utf-8"
    src_dir = str(Path(__file__).parent.parent / "src")
    if "PYTHONPATH" in test_env:
        test_env["PYTHONPATH"] = src_dir + os.pathsep + test_env["PYTHONPATH"]
    else:
        test_env["PYTHONPATH"] = src_dir

    server_cmd = f"{sys.executable} {mock_server_path}"

    # Pre-initialize database file & schemas to avoid concurrent migration lockouts
    db_init = Database(str(db_path))
    await db_init.connect()
    await db_init.close()

    # Helper to run a short proxy session
    async def run_proxy_session(name: str):
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "mcp_debugger.cli",
            "proxy",
            "--server",
            server_cmd,
            "--name",
            name,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env=test_env,
        )

        assert proc.stdin is not None
        assert proc.stdout is not None

        try:
            # Send 10 messages
            for i in range(10):
                req = {
                    "jsonrpc": "2.0",
                    "id": i,
                    "method": "ping",
                    "params": {"client": name, "num": i},
                }
                proc.stdin.write(json.dumps(req).encode("utf-8") + b"\n")
                try:
                    await proc.stdin.drain()
                except (ConnectionResetError, BrokenPipeError):
                    # Subprocess exited before all writes completed — expected in stress tests
                    break
                # Read response
                try:
                    await asyncio.wait_for(proc.stdout.readline(), timeout=2.0)
                except asyncio.TimeoutError:
                    break
        finally:
            if proc.stdin:
                try:
                    proc.stdin.close()
                except Exception:
                    pass
            try:
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                    await proc.wait()
                except Exception:
                    pass

    # Run two proxies concurrently
    await asyncio.gather(run_proxy_session("proxy-session-1"), run_proxy_session("proxy-session-2"))

    # Verify both sessions were recorded correctly in DB
    db = Database(str(db_path))
    await db.connect()
    sessions = await db.get_sessions()
    assert len(sessions) == 2
    friendly_names = {s["friendly_name"] for s in sessions}
    assert "proxy-session-1" in friendly_names
    assert "proxy-session-2" in friendly_names

    await db.close()


@pytest.mark.asyncio
async def test_large_message_limit_stress(tmp_path: Path) -> None:
    """Stress test: Send a 5MB message through the proxy to ensure no crash.
    We use 5MB instead of 50MB to prevent memory exhaustion/slow execution on test runner.
    """
    db_path = tmp_path / "large_msg.db"
    mock_server_path = tmp_path / "mock_echo_server.py"

    mock_server_code = """
import sys
import json

while True:
    line = sys.stdin.readline()
    if not line:
        break
    if not line.strip():
        continue
    try:
        msg = json.loads(line)
        if "id" in msg:
            resp = {"jsonrpc": "2.0", "id": msg["id"], "result": "ok"}
            sys.stdout.write(json.dumps(resp) + "\\n")
            sys.stdout.flush()
    except Exception:
        pass
"""
    mock_server_path.write_text(mock_server_code, encoding="utf-8")

    test_env = os.environ.copy()
    test_env["MCP_DEBUGGER_DATABASE_PATH"] = str(db_path)
    test_env["PYTHONIOENCODING"] = "utf-8"
    src_dir = str(Path(__file__).parent.parent / "src")
    if "PYTHONPATH" in test_env:
        test_env["PYTHONPATH"] = src_dir + os.pathsep + test_env["PYTHONPATH"]
    else:
        test_env["PYTHONPATH"] = src_dir

    server_cmd = f"{sys.executable} {mock_server_path}"

    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "mcp_debugger.cli",
        "proxy",
        "--server",
        server_cmd,
        "--name",
        "large-msg-session",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        env=test_env,
    )

    assert proc.stdin is not None
    assert proc.stdout is not None

    large_payload = "x" * 5_000_000  # 5MB
    large_req = {"jsonrpc": "2.0", "id": 999, "method": "large", "params": {"data": large_payload}}

    try:
        # Write large request
        proc.stdin.write(json.dumps(large_req).encode("utf-8") + b"\n")
        await proc.stdin.drain()

        # Read response
        resp_line = await asyncio.wait_for(proc.stdout.readline(), timeout=10.0)
        assert resp_line != b""
        resp = json.loads(resp_line.decode("utf-8"))
        assert resp["id"] == 999
        assert resp["result"] == "ok"
    finally:
        if proc.stdin:
            try:
                proc.stdin.close()
            except Exception:
                pass
        try:
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass
