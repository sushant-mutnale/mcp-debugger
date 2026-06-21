import asyncio
import unittest
from typing import Any, List, Optional
from unittest.mock import MagicMock, patch
import pytest

from mcp_debugger.proxy.stdio_proxy import StdioProxy, split_command
from mcp_debugger.storage.database import Database


class MockStreamWriter:
    """Mock writer simulating subprocess.stdin."""

    def __init__(self, event: Optional[asyncio.Event] = None) -> None:
        self.written_data: List[bytes] = []
        self.event = event

    def write(self, data: bytes) -> None:
        self.written_data.append(data)
        if self.event:
            self.event.set()

    async def drain(self) -> None:
        pass


class MockStreamReader:
    """Mock reader simulating subprocess.stdout."""

    def __init__(self, lines: List[str], event: Optional[asyncio.Event] = None) -> None:
        self.lines = [line.encode("utf-8") for line in lines]
        self.idx = 0
        self.event = event

    async def readline(self) -> bytes:
        if self.event:
            await self.event.wait()
        if self.idx >= len(self.lines):
            self.idx += 1
            return b""  # EOF
        val = self.lines[self.idx]
        self.idx += 1
        return val


class MockProcess:
    """Mock process simulating asyncio.subprocess.Process."""

    def __init__(
        self, stdout_lines: List[str], exit_code: int = 0, event: Optional[asyncio.Event] = None
    ) -> None:
        self.stdin = MockStreamWriter(event)
        self.stdout = MockStreamReader(stdout_lines, event)
        self.exit_code = exit_code
        self.terminated = False
        self.killed = False

    async def wait(self) -> int:
        for _ in range(200):
            if self.stdout.idx > len(self.stdout.lines):
                break
            await asyncio.sleep(0.005)
        await asyncio.sleep(0.05)
        return self.exit_code

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True


def test_split_command() -> None:
    """Verify shlex command splitting behaviors."""
    cmd = 'npx -y @server --arg "nested spaces"'
    args = split_command(cmd)
    assert args == ["npx", "-y", "@server", "--arg", "nested spaces"]


@pytest.mark.asyncio
async def test_proxy_successful_forwarding(
    temp_db: Database, capsys: pytest.CaptureFixture[str]
) -> None:
    """Verify correct piping, forwarding, and DB logging under standard execution conditions."""
    session_id = await temp_db.create_session("mock-server")
    event = asyncio.Event()

    # Mock subprocess output lines
    mock_process = MockProcess(
        stdout_lines=['{"jsonrpc": "2.0", "id": "msg-101", "result": "pong"}\n'],
        event=event,
    )

    # Mock client standard input lines
    mock_stdin = MagicMock()
    mock_stdin.readline.side_effect = [
        '{"jsonrpc": "2.0", "id": "msg-101", "method": "ping"}\n',
        "",  # EOF
    ]

    proxy = StdioProxy(
        server_command="mock-server",
        database=temp_db,
        session_id=session_id,
        verbose=True,
    )

    with (
        patch("asyncio.create_subprocess_exec", return_value=mock_process),
        patch("sys.stdin", mock_stdin),
    ):
        exit_code = await proxy.run()
        assert exit_code == 0

    # Assert client input was written to server stdin
    server_stdin_data = b"".join(mock_process.stdin.written_data).decode("utf-8")
    assert '"method": "ping"' in server_stdin_data

    # Assert server output was written to client stdout (captured by capsys)
    captured = capsys.readouterr()
    assert '"result": "pong"' in captured.out

    # Verify database logs
    messages = await temp_db.get_messages(session_id)
    assert len(messages) == 2

    # Check client to server request
    assert messages[0]["direction"] == "client_to_server"
    assert messages[0]["method"] == "ping"
    assert messages[0]["message_type"] == "request"

    # Check server to client response and latency matching
    assert messages[1]["direction"] == "server_to_client"
    assert messages[1]["method"] == "ping"
    assert messages[1]["message_type"] == "response"
    assert messages[1]["latency_ms"] is not None


@pytest.mark.asyncio
async def test_proxy_server_crash(temp_db: Database) -> None:
    """Verify that proxy returns the server exit code if the server crashes."""
    session_id = await temp_db.create_session("mock-server")

    # Mock crashing subprocess
    mock_process = MockProcess(stdout_lines=[], exit_code=5)

    mock_stdin = MagicMock()
    mock_stdin.readline.side_effect = [
        ""  # EOF
    ]

    proxy = StdioProxy(
        server_command="mock-server",
        database=temp_db,
        session_id=session_id,
    )

    with (
        patch("asyncio.create_subprocess_exec", return_value=mock_process),
        patch("sys.stdin", mock_stdin),
    ):
        exit_code = await proxy.run()
        assert exit_code == 5

    # Check session closed with error
    session = await temp_db.get_session(session_id)
    assert session is not None
    assert session["status"] == "error"


@pytest.mark.asyncio
async def test_proxy_malformed_json(temp_db: Database, capsys: pytest.CaptureFixture[str]) -> None:
    """Verify malformed JSON is handled correctly:
    - Client non-JSON: warning to stderr + stored in errors table.
    - Server non-JSON: log to stderr + stored in server_logs, NOT forwarded to stdout.
    """
    session_id = await temp_db.create_session("mock-server")
    event = asyncio.Event()

    mock_process = MockProcess(
        stdout_lines=["invalid server json\n"],
        event=event,
    )

    mock_stdin = MagicMock()
    mock_stdin.readline.side_effect = [
        "invalid client json\n",
        "",  # EOF
    ]

    proxy = StdioProxy(
        server_command="mock-server",
        database=temp_db,
        session_id=session_id,
    )

    with (
        patch("asyncio.create_subprocess_exec", return_value=mock_process),
        patch("sys.stdin", mock_stdin),
    ):
        exit_code = await proxy.run()
        assert exit_code == 0

    captured = capsys.readouterr()

    # Server non-JSON must NOT reach client stdout
    assert "invalid server json" not in captured.out

    # Server non-JSON must appear in stderr as a server log line
    assert "server log" in captured.err
    assert "invalid server json" in captured.err

    # Client non-JSON still triggers the existing warning in stderr
    assert "Intercepted non-JSON line" in captured.err

    # Client non-JSON → stored in errors table
    errors = await temp_db.get_errors(session_id)
    assert len(errors) == 1
    assert errors[0]["error_type"] == "protocol"
    assert "invalid client json" in errors[0]["stack_trace"]

    # Server non-JSON → stored in server_logs table (not errors)
    server_logs = await temp_db.get_server_logs(session_id)
    assert len(server_logs) == 1
    assert "invalid server json" in server_logs[0]["raw_text"]
    assert server_logs[0]["source"] == "server_stdout"


@pytest.mark.asyncio
async def test_proxy_empty_command(temp_db: Database) -> None:
    """Verify that proxy exits with error if the server command parses to empty."""
    session_id = await temp_db.create_session("")
    proxy = StdioProxy(
        server_command="",
        database=temp_db,
        session_id=session_id,
    )
    exit_code = await proxy.run()
    assert exit_code == 1


@pytest.mark.asyncio
async def test_proxy_exec_not_found(temp_db: Database) -> None:
    """Verify that proxy falls back to shell invocation if executable is not found."""
    session_id = await temp_db.create_session("not-found-exec")
    mock_process = MockProcess(stdout_lines=[])
    mock_stdin = MagicMock()
    mock_stdin.readline.side_effect = [""]

    proxy = StdioProxy(
        server_command="not-found-exec",
        database=temp_db,
        session_id=session_id,
    )

    with (
        patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError),
        patch("asyncio.create_subprocess_shell", return_value=mock_process) as mock_shell,
        patch("sys.stdin", mock_stdin),
    ):
        exit_code = await proxy.run()
        assert exit_code == 0
        mock_shell.assert_called_once_with(
            "not-found-exec",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=None,
        )


@pytest.mark.asyncio
async def test_proxy_exec_generic_error(temp_db: Database) -> None:
    """Verify that proxy returns 1 if exec raises a non-FileNotFoundException."""
    session_id = await temp_db.create_session("error-exec")
    mock_stdin = MagicMock()
    mock_stdin.readline.side_effect = [""]

    proxy = StdioProxy(
        server_command="error-exec",
        database=temp_db,
        session_id=session_id,
    )

    with (
        patch("asyncio.create_subprocess_exec", side_effect=RuntimeError("exec error")),
        patch("sys.stdin", mock_stdin),
    ):
        exit_code = await proxy.run()
        assert exit_code == 1


@pytest.mark.asyncio
async def test_proxy_shell_generic_error(temp_db: Database) -> None:
    """Verify that proxy returns 1 if fallback shell execution itself fails."""
    session_id = await temp_db.create_session("error-shell")
    mock_stdin = MagicMock()
    mock_stdin.readline.side_effect = [""]

    proxy = StdioProxy(
        server_command="error-shell",
        database=temp_db,
        session_id=session_id,
    )

    with (
        patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError),
        patch("asyncio.create_subprocess_shell", side_effect=RuntimeError("shell error")),
        patch("sys.stdin", mock_stdin),
    ):
        exit_code = await proxy.run()
        assert exit_code == 1


@pytest.mark.asyncio
async def test_proxy_validation_failure_but_valid_json(temp_db: Database) -> None:
    """Verify raw log fallback when JSON structure does not match JSON-RPC models."""
    session_id = await temp_db.create_session("mock-server")
    event = asyncio.Event()
    mock_process = MockProcess(stdout_lines=['{"server_key": "val"}\n'], event=event)
    mock_stdin = MagicMock()
    mock_stdin.readline.side_effect = [
        '{"client_key": "val"}\n',
        "",  # EOF
    ]

    proxy = StdioProxy(
        server_command="mock-server",
        database=temp_db,
        session_id=session_id,
        verbose=True,
    )

    with (
        patch("asyncio.create_subprocess_exec", return_value=mock_process),
        patch("sys.stdin", mock_stdin),
    ):
        exit_code = await proxy.run()
        assert exit_code == 0

    messages = await temp_db.get_messages(session_id)
    assert len(messages) == 2
    assert messages[0]["direction"] == "client_to_server"
    assert messages[0]["method"] is None
    assert messages[1]["direction"] == "server_to_client"


class MockTimeoutProcess:
    """Mock process that simulates a timeout during terminate."""

    def __init__(self) -> None:
        self.stdin = MockStreamWriter()
        self.stdout = MockStreamReader([])
        self.exit_code = -9
        self.terminated = False
        self.killed = False
        self.wait_call_count = 0

    async def wait(self) -> int:
        self.wait_call_count += 1
        if self.wait_call_count == 1:
            await asyncio.sleep(10.0)
            return -1
        return -9

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True


@pytest.mark.asyncio
async def test_proxy_terminate_timeout(temp_db: Database) -> None:
    """Verify that process is forcefully killed if terminate times out."""
    session_id = await temp_db.create_session("mock-server")
    mock_process = MockTimeoutProcess()
    mock_stdin = MagicMock()
    mock_stdin.readline.side_effect = [""]

    proxy = StdioProxy(
        server_command="mock-server",
        database=temp_db,
        session_id=session_id,
    )

    original_wait_for = asyncio.wait_for

    async def mock_wait_for(aw: Any, timeout: Optional[float], **kwargs: Any) -> Any:
        if timeout == 3.0:
            try:
                aw.close()
            except AttributeError:
                pass
            raise asyncio.TimeoutError()
        return await original_wait_for(aw, timeout, **kwargs)

    with (
        patch("asyncio.create_subprocess_exec", return_value=mock_process),
        patch("sys.stdin", mock_stdin),
        patch("asyncio.wait_for", side_effect=mock_wait_for),
    ):
        task = asyncio.create_task(proxy.run())
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        assert mock_process.terminated
        assert mock_process.killed


@pytest.mark.asyncio
async def test_proxy_stdin_read_error(temp_db: Database) -> None:
    """Verify that exception in stdin background thread reading does not crash proxy."""
    session_id = await temp_db.create_session("mock-server")
    mock_process = MockProcess(stdout_lines=[])
    mock_stdin = MagicMock()
    mock_stdin.readline.side_effect = Exception("Simulated read error")

    proxy = StdioProxy(
        server_command="mock-server",
        database=temp_db,
        session_id=session_id,
    )

    with (
        patch("asyncio.create_subprocess_exec", return_value=mock_process),
        patch("sys.stdin", mock_stdin),
    ):
        exit_code = await proxy.run()
        assert exit_code == 0


class MockExceptionProcess:
    """Mock process where stdout readline raises an OSError."""

    def __init__(self) -> None:
        self.stdin = MockStreamWriter()
        self.stdout = MagicMock()
        self.stdout.readline.side_effect = OSError("Simulated read error")
        self.exit_code = 0

    async def wait(self) -> int:
        await asyncio.sleep(0.01)
        return self.exit_code

    def terminate(self) -> None:
        pass


@pytest.mark.asyncio
async def test_proxy_server_stdout_read_error(temp_db: Database) -> None:
    """Verify that exceptions during server stdout readline are caught."""
    session_id = await temp_db.create_session("mock-server")
    mock_process = MockExceptionProcess()
    mock_stdin = MagicMock()
    mock_stdin.readline.side_effect = [""]

    proxy = StdioProxy(
        server_command="mock-server",
        database=temp_db,
        session_id=session_id,
    )

    with (
        patch("asyncio.create_subprocess_exec", return_value=mock_process),
        patch("sys.stdin", mock_stdin),
    ):
        exit_code = await proxy.run()
        assert exit_code == 0


@pytest.mark.asyncio
async def test_proxy_empty_line(temp_db: Database) -> None:
    """Verify that empty/whitespace lines in stdin/stdout are ignored from logs."""
    session_id = await temp_db.create_session("mock-server")
    mock_process = MockProcess(stdout_lines=["\n", '{"jsonrpc": "2.0", "id": 1, "result": "ok"}\n'])
    mock_stdin = MagicMock()
    mock_stdin.readline.side_effect = ["\n", '{"jsonrpc": "2.0", "id": 1, "method": "ping"}\n', ""]

    proxy = StdioProxy(
        server_command="mock-server",
        database=temp_db,
        session_id=session_id,
    )

    with (
        patch("asyncio.create_subprocess_exec", return_value=mock_process),
        patch("sys.stdin", mock_stdin),
    ):
        exit_code = await proxy.run()
        assert exit_code == 0

    messages = await temp_db.get_messages(session_id)
    assert len(messages) == 2


class MockWriteErrorStreamWriter:
    """Mock writer that raises OSError on write."""

    def write(self, data: bytes) -> None:
        raise OSError("Simulated write error")

    async def drain(self) -> None:
        pass


class MockWriteErrorProcess:
    """Mock process with a stdin writer that fails on write."""

    def __init__(self) -> None:
        self.stdin = MockWriteErrorStreamWriter()
        self.stdout = MockStreamReader([])
        self.exit_code = 0

    async def wait(self) -> int:
        await asyncio.sleep(0.01)
        return self.exit_code

    def terminate(self) -> None:
        pass


@pytest.mark.asyncio
async def test_proxy_client_forward_error(temp_db: Database) -> None:
    """Verify that client stdin forwarding fails gracefully on write errors."""
    session_id = await temp_db.create_session("mock-server")
    mock_process = MockWriteErrorProcess()
    mock_stdin = MagicMock()
    mock_stdin.readline.side_effect = ['{"jsonrpc": "2.0", "id": 1, "method": "ping"}\n', ""]

    proxy = StdioProxy(
        server_command="mock-server",
        database=temp_db,
        session_id=session_id,
    )

    with (
        patch("asyncio.create_subprocess_exec", return_value=mock_process),
        patch("sys.stdin", mock_stdin),
    ):
        exit_code = await proxy.run()
        assert exit_code == 0


@pytest.mark.asyncio
async def test_proxy_database_failure(temp_db: Database) -> None:
    """Verify that database errors during logging do not crash standard I/O forwarding."""
    session_id = await temp_db.create_session("mock-server")
    mock_process = MockProcess(
        stdout_lines=['{"jsonrpc": "2.0", "id": "msg-101", "result": "pong"}\n']
    )
    mock_stdin = MagicMock()
    mock_stdin.readline.side_effect = [
        '{"jsonrpc": "2.0", "id": "msg-101", "method": "ping"}\n',
        "invalid JSON\n",
        "",  # EOF
    ]

    proxy = StdioProxy(
        server_command="mock-server",
        database=temp_db,
        session_id=session_id,
    )

    with (
        patch.object(temp_db, "log_message", side_effect=RuntimeError("db error")),
        patch.object(temp_db, "log_error", side_effect=RuntimeError("db error")),
        patch.object(temp_db, "close_session", side_effect=RuntimeError("db error")),
        patch("asyncio.create_subprocess_exec", return_value=mock_process),
        patch("sys.stdin", mock_stdin),
    ):
        exit_code = await proxy.run()
        assert exit_code == 0


@pytest.mark.asyncio
async def test_proxy_large_message_and_tools_list(
    temp_db: Database, capsys: pytest.CaptureFixture[str]
) -> None:
    """Verify handling of large messages (warning/truncation limits) and tools list logging."""
    import json

    session_id = await temp_db.create_session("mock-server")

    # Message larger than WARN_SIZE but below MAX_SIZE (e.g. 1.5MB)
    warn_payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "warn",
        "params": "x" * (1024 * 1024 + 100),
    }
    warn_line = json.dumps(warn_payload)

    # Message larger than MAX_SIZE (e.g. 11MB)
    max_payload = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "max",
        "params": "y" * (10 * 1024 * 1024 + 100),
    }
    max_line = json.dumps(max_payload)

    # Standard tool list response
    tools_payload = {
        "jsonrpc": "2.0",
        "id": 3,
        "result": {
            "tools": [
                {"name": "my_tool", "description": "some tool", "inputSchema": {"type": "object"}}
            ]
        },
    }
    tools_line = json.dumps(tools_payload)

    mock_process = MockProcess(stdout_lines=[tools_line + "\n"])
    mock_stdin = MagicMock()
    mock_stdin.readline.side_effect = [
        warn_line + "\n",
        max_line + "\n",
        "",  # EOF
    ]

    proxy = StdioProxy(
        server_command="mock-server",
        database=temp_db,
        session_id=session_id,
        verbose=True,
    )

    with (
        patch("asyncio.create_subprocess_exec", return_value=mock_process),
        patch("sys.stdin", mock_stdin),
    ):
        exit_code = await proxy.run()
        assert exit_code == 0

    captured = capsys.readouterr()
    assert "Large message from client_to_server" in captured.err
    assert "Message exceeds 10 MB limit" in captured.err

    # Check that tools were registered in database
    tools = await temp_db.get_tools(session_id)
    assert len(tools) == 1
    assert tools[0]["name"] == "my_tool"


@pytest.mark.asyncio
async def test_proxy_cleanup_exceptions(temp_db: Database) -> None:
    """Verify cleanup exception handling for ProcessLookupError and other errors."""
    session_id = await temp_db.create_session("mock-server")
    proxy = StdioProxy(
        server_command="mock-server",
        database=temp_db,
        session_id=session_id,
    )

    # 1. ProcessLookupError on terminate
    mock_process1 = MagicMock()
    mock_process1.terminate.side_effect = ProcessLookupError()
    proxy.process = mock_process1
    await proxy._cleanup()
    assert proxy.process is None

    # 2. General Exception on terminate
    mock_process2 = MagicMock()
    mock_process2.terminate.side_effect = RuntimeError("Generic termination failure")
    proxy.process = mock_process2
    await proxy._cleanup()
    assert proxy.process is None


@pytest.mark.asyncio
async def test_proxy_handle_message_database_errors(
    temp_db: Database, capsys: pytest.CaptureFixture[str]
) -> None:
    """Verify stdio proxy handles database failures inside message loop."""
    import json

    session_id = await temp_db.create_session("mock-server")
    proxy = StdioProxy(
        server_command="mock-server",
        database=temp_db,
        session_id=session_id,
        verbose=True,
    )

    # 1. log_message raises database error for valid JSON (both standard valid jsonrpc schema and raw fallback mismatch)
    # We want standard log to fail and validation fallback log to ALSO fail
    with patch.object(temp_db, "log_message", side_effect=RuntimeError("Database failure")):
        # A. Valid JSON-RPC: standard validation succeeds, log_message fails -> covers standard db error
        payload_valid_rpc = '{"jsonrpc": "2.0", "id": 1, "method": "ping"}\n'
        await proxy._handle_message(payload_valid_rpc, "client_to_server")
        captured_valid = capsys.readouterr()
        assert "Failed to log message to database" in captured_valid.err

        # B. Invalid JSON-RPC: standard validation fails, raw log fallback fails -> covers raw db error
        payload_invalid_rpc = '{"some_random_key": "some_value"}\n'
        await proxy._handle_message(payload_invalid_rpc, "client_to_server")
        captured_invalid = capsys.readouterr()
        assert "Failed to log raw message to database" in captured_invalid.err

    # 2. log_error raises database error when logging a classified error
    # We log a JSON-RPC error response to trigger ErrorClassifier
    err_payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "error": {"code": -32601, "message": "Method not found"},
    }
    # Mock log_message to succeed, but log_error to fail
    with patch.object(
        temp_db, "log_message", new_callable=unittest.mock.AsyncMock, return_value=123
    ):
        with patch.object(
            temp_db, "log_error", side_effect=RuntimeError("Log error database failure")
        ):
            await proxy._handle_message(json.dumps(err_payload), "server_to_client")
            captured = capsys.readouterr()
            assert "Failed to log classified error to database" in captured.err

    # 3. Invalid error code (non-integer error code string)
    invalid_code_payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "error": {"code": "non-integer-code", "message": "Method not found"},
    }
    with patch.object(
        temp_db, "log_message", new_callable=unittest.mock.AsyncMock, return_value=123
    ):
        with patch.object(
            temp_db, "log_error", new_callable=unittest.mock.AsyncMock
        ) as mock_log_error:
            await proxy._handle_message(json.dumps(invalid_code_payload), "server_to_client")
            # Should have been logged with error_code=None
            mock_log_error.assert_called_once()
            _, kwargs = mock_log_error.call_args
            assert kwargs["error_code"] is None


@pytest.mark.asyncio
async def test_proxy_stdin_exception_and_missing_process(temp_db: Database) -> None:
    """Verify proxy behavior when writing to stdin raises an exception or process/stdout is missing."""
    session_id = await temp_db.create_session("mock-server")

    # 1. Stdin write exception
    proxy1 = StdioProxy(
        server_command="mock-server",
        database=temp_db,
        session_id=session_id,
    )

    mock_process = MockProcess(stdout_lines=[])
    # Mock write to raise Exception
    mock_process.stdin.write = MagicMock(side_effect=RuntimeError("Pipe error"))
    proxy1.process = mock_process

    # Put a line and call the loop
    queue = asyncio.Queue()
    await queue.put("hello\n")
    await proxy1._client_to_server_loop(queue)

    # 2. Missing process or stdout checks
    proxy2 = StdioProxy(
        server_command="mock-server",
        database=temp_db,
        session_id=session_id,
    )
    # process is None
    proxy2.process = None
    # Loops and monitors should return immediately
    await proxy2._server_to_client_loop()
    await proxy2._monitor_subprocess()
