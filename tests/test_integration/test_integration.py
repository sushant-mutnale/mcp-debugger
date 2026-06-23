import asyncio
import json
import os
import sys
from pathlib import Path
import pytest

from mcp_debugger.storage.database import Database


@pytest.mark.asyncio
async def test_integration_proxy_to_inspect(tmp_path: Path) -> None:
    print("\n[TEST] 1. Setup paths")
    temp_db_path = tmp_path / "integration_test.db"
    mock_server_path = tmp_path / "mock_mcp_server.py"

    print("[TEST] 2. Write mock MCP server")
    mock_server_code = """
import sys
import json

def main():
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            msg = json.loads(line)
            msg_id = msg.get("id")
            method = msg.get("method")
            if method == "initialize":
                resp = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "protocolVersion": "2025-03-26",
                        "serverInfo": {"name": "mock-server", "version": "1.0"},
                        "capabilities": {}
                    }
                }
                sys.stdout.write(json.dumps(resp) + "\\n")
                sys.stdout.flush()
            elif method == "tools/list":
                resp = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "tools": [
                            {
                                "name": "mock_tool",
                                "description": "A mock tool for testing",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "param1": {"type": "string"}
                                    }
                                }
                            }
                        ]
                    }
                }
                sys.stdout.write(json.dumps(resp) + "\\n")
                sys.stdout.flush()
        except Exception as e:
            sys.stderr.write(f"Mock server error: {e}\\n")
            sys.stderr.flush()

if __name__ == "__main__":
    main()
"""
    mock_server_path.write_text(mock_server_code, encoding="utf-8")

    test_env = os.environ.copy()
    test_env["MCP_DEBUGGER_DATABASE_PATH"] = str(temp_db_path)
    test_env["PYTHONIOENCODING"] = "utf-8"
    src_dir = str(Path(__file__).parent.parent.parent / "src")
    if "PYTHONPATH" in test_env:
        test_env["PYTHONPATH"] = src_dir + os.pathsep + test_env["PYTHONPATH"]
    else:
        test_env["PYTHONPATH"] = src_dir

    print("[TEST] 3. Launch proxy subprocess")
    server_cmd = f"{sys.executable} {mock_server_path}"

    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "mcp_debugger.cli",
        "proxy",
        "--server",
        server_cmd,
        "--name",
        "integration-test-session",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=None,
        env=test_env,
    )

    assert proc.stdin is not None
    assert proc.stdout is not None

    try:
        print("[TEST] 4A. Send initialize request")
        init_req = {
            "jsonrpc": "2.0",
            "id": 1001,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "clientInfo": {"name": "test-integration-client", "version": "1.0"},
            },
        }
        proc.stdin.write(json.dumps(init_req).encode("utf-8") + b"\n")
        await proc.stdin.drain()

        print("[TEST] 4A. Read initialize response")
        try:
            line1_bytes = await asyncio.wait_for(proc.stdout.readline(), timeout=4.0)
        except asyncio.TimeoutError:
            raise AssertionError("Timeout waiting for response.")

        line1 = line1_bytes.decode("utf-8").strip()
        print(f"[TEST] 4A. Received: {line1}")
        if not line1:
            raise AssertionError("Subprocess stdout closed empty.")

        init_resp = json.loads(line1)
        assert init_resp.get("id") == 1001
        assert "mock-server" in init_resp["result"]["serverInfo"]["name"]

        print("[TEST] 4B. Send notifications/initialized")
        init_notif = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        proc.stdin.write(json.dumps(init_notif).encode("utf-8") + b"\n")
        await proc.stdin.drain()

        print("[TEST] 4C. Send tools/list request")
        tools_req = {"jsonrpc": "2.0", "id": 1002, "method": "tools/list"}
        proc.stdin.write(json.dumps(tools_req).encode("utf-8") + b"\n")
        await proc.stdin.drain()

        print("[TEST] 4C. Read tools/list response")
        try:
            line2_bytes = await asyncio.wait_for(proc.stdout.readline(), timeout=4.0)
        except asyncio.TimeoutError:
            raise AssertionError("Timeout waiting for tools/list response")
        line2 = line2_bytes.decode("utf-8").strip()
        print(f"[TEST] 4C. Received: {line2}")
        assert line2 != ""
        tools_resp = json.loads(line2)
        assert tools_resp.get("id") == 1002
        assert tools_resp["result"]["tools"][0]["name"] == "mock_tool"

    finally:
        print("[TEST] 5. Shut down proxy by closing stdin")
        proc.stdin.close()

        print("[TEST] 5. Waiting for proxy process to exit")
        try:
            await asyncio.wait_for(proc.wait(), timeout=4.0)
            print("[TEST] 5. Proxy process exited normally")
        except asyncio.TimeoutError:
            print("[TEST] 5. Proxy process timed out, killing it...")
            proc.kill()
            await proc.wait()
            print("[TEST] 5. Proxy process killed")

        err_str = "<stderr not captured/inherited>"
        if proc.stderr is not None:
            try:
                err_bytes = await asyncio.wait_for(proc.stderr.read(), timeout=1.0)
                err_str = err_bytes.decode("utf-8")
            except Exception:
                err_str = "<timeout/error reading stderr>"
        print(f"[TEST] 5. Proxy stderr:\n{err_str}")

    print("[TEST] 6. Verify Database Contents")
    db = Database(db_path=str(temp_db_path))
    await db.connect()

    sessions = await db.get_sessions()
    print(f"[TEST] 6. Sessions in database: {sessions}")
    assert len(sessions) == 1
    session = sessions[0]
    assert session["friendly_name"] == "integration-test-session"
    assert session["status"] == "completed"

    messages = await db.get_messages(session_id=session["id"])
    assert len(messages) == 5

    conn = await db._get_conn()
    async with conn.execute(
        "SELECT name, description FROM tools WHERE session_id = ?", (session["id"],)
    ) as cursor:
        rows = list(await cursor.fetchall())
        assert len(rows) == 1
        assert rows[0][0] == "mock_tool"
        assert rows[0][1] == "A mock tool for testing"

    await db.close()
    print("[TEST] 6. Database closed")

    print("[TEST] 7. Run CLI inspect command")
    proc_inspect = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "mcp_debugger.cli",
        "inspect",
        str(session["id"]),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=test_env,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc_inspect.communicate(), timeout=5.0)
    except asyncio.TimeoutError:
        proc_inspect.kill()
        stdout, stderr = await proc_inspect.communicate()
        print(
            f"[TEST] 7. inspect command timed out. Stdout:\n{stdout.decode('utf-8')}\nStderr:\n{stderr.decode('utf-8')}"
        )
        raise AssertionError("inspect command timed out")
    assert proc_inspect.returncode == 0
    stdout_str = stdout.decode("utf-8")
    assert "client → server" in stdout_str
    assert "server → client" in stdout_str
    assert "initialize" in stdout_str
    assert "tools/list" in stdout_str
    assert "mock_tool" in stdout_str
    print("[TEST] 7. inspect command success")

    print("[TEST] 8. Run CLI inspect command --json")
    proc_inspect_json = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "mcp_debugger.cli",
        "inspect",
        str(session["id"]),
        "--json",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=test_env,
    )
    try:
        stdout_j, stderr_j = await asyncio.wait_for(proc_inspect_json.communicate(), timeout=5.0)
    except asyncio.TimeoutError:
        proc_inspect_json.kill()
        stdout_j, stderr_j = await proc_inspect_json.communicate()
        print(
            f"[TEST] 8. inspect --json command timed out. Stdout:\n{stdout_j.decode('utf-8')}\nStderr:\n{stderr_j.decode('utf-8')}"
        )
        raise AssertionError("inspect --json command timed out")
    assert proc_inspect_json.returncode == 0
    parsed = json.loads(stdout_j.decode("utf-8"))
    assert len(parsed) == 5
    assert parsed[0]["method"] == "initialize"
    methods = [m["method"] for m in parsed]
    assert "initialize" in methods
    assert "notifications/initialized" in methods
    assert "tools/list" in methods
    print("[TEST] 8. inspect --json success")

    print("[TEST] 9. Run CLI tools command")
    proc_tools = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "mcp_debugger.cli",
        "tools",
        str(session["id"]),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=test_env,
    )
    try:
        stdout_t, stderr_t = await asyncio.wait_for(proc_tools.communicate(), timeout=5.0)
    except asyncio.TimeoutError:
        proc_tools.kill()
        stdout_t, stderr_t = await proc_tools.communicate()
        print(
            f"[TEST] 9. tools command timed out. Stdout:\n{stdout_t.decode('utf-8')}\nStderr:\n{stderr_t.decode('utf-8')}"
        )
        raise AssertionError("tools command timed out")
    assert proc_tools.returncode == 0
    stdout_t_str = stdout_t.decode("utf-8")
    assert "mock_tool" in stdout_t_str
    assert "A mock tool for testing" in stdout_t_str
    # Our mock server did not receive tools/call in this E2E test yet, so calls count is 0
    assert "0" in stdout_t_str
    print("[TEST] 9. tools command success")

    print("[TEST] 10. Run CLI tools command --json")
    proc_tools_json = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "mcp_debugger.cli",
        "tools",
        str(session["id"]),
        "--json",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=test_env,
    )
    try:
        stdout_tj, stderr_tj = await asyncio.wait_for(proc_tools_json.communicate(), timeout=5.0)
    except asyncio.TimeoutError:
        proc_tools_json.kill()
        stdout_tj, stderr_tj = await proc_tools_json.communicate()
        print(
            f"[TEST] 10. tools --json command timed out. Stdout:\n{stdout_tj.decode('utf-8')}\nStderr:\n{stderr_tj.decode('utf-8')}"
        )
        raise AssertionError("tools --json command timed out")
    assert proc_tools_json.returncode == 0
    parsed_tj = json.loads(stdout_tj.decode("utf-8"))
    assert len(parsed_tj) == 1
    assert parsed_tj[0]["name"] == "mock_tool"
    assert parsed_tj[0]["description"] == "A mock tool for testing"
    assert parsed_tj[0]["calls"] == 0
    assert parsed_tj[0]["input_schema"]["properties"]["param1"]["type"] == "string"
    print("[TEST] 10. tools --json success")

    print("[TEST] 11. Run CLI tools command --detail")
    proc_tools_detail = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "mcp_debugger.cli",
        "tools",
        str(session["id"]),
        "--detail",
        "mock_tool",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=test_env,
    )
    try:
        stdout_td, stderr_td = await asyncio.wait_for(proc_tools_detail.communicate(), timeout=5.0)
    except asyncio.TimeoutError:
        proc_tools_detail.kill()
        stdout_td, stderr_td = await proc_tools_detail.communicate()
        print(
            f"[TEST] 11. tools --detail command timed out. Stdout:\n{stdout_td.decode('utf-8')}\nStderr:\n{stderr_td.decode('utf-8')}"
        )
        raise AssertionError("tools --detail command timed out")
    assert proc_tools_detail.returncode == 0
    stdout_td_str = stdout_td.decode("utf-8")
    assert "Tool Schema: mock_tool" in stdout_td_str
    assert "param1" in stdout_td_str
    print("[TEST] 11. tools --detail success")
