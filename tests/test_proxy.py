"""Unit tests for the stdio proxy core."""

import asyncio
import os
import tempfile
from typing import Any, AsyncGenerator, List, Optional
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


@pytest.fixture
async def temp_db() -> AsyncGenerator[Database, None]:
    """Fixture returning a temporary Database connection."""
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
    """Verify malformed JSON does not crash proxy but triggers warning logs."""
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

    # Ensure stdout still received the raw line
    captured = capsys.readouterr()
    assert "invalid server json" in captured.out
    assert "warning" in captured.err

    # Ensure warnings printed to stderr contain indicators
    assert "Intercepted non-JSON line" in captured.err

    # Check that error logs are stored in the database
    errors = await temp_db.get_errors(session_id)
    assert len(errors) == 2
    assert errors[0]["error_type"] == "protocol"
    assert "invalid client json" in errors[0]["stack_trace"]
    assert "invalid server json" in errors[1]["stack_trace"]


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
