import sys
import asyncio
from typing import Any
from unittest.mock import patch
import pytest
from typer.testing import CliRunner

from mcp_debugger.cli import app
from mcp_debugger.storage.database import Database


def test_validate_help_or_missing(runner: CliRunner) -> None:
    """Verify validate command fails when neither session_id nor --server is provided."""
    result = runner.invoke(app, ["validate"])
    assert result.exit_code == 1
    assert "Error: Please specify a session_id" in result.stdout


def test_validate_both(runner: CliRunner) -> None:
    """Verify validate command fails when both session_id and --server are provided."""
    result = runner.invoke(app, ["validate", "1", "--server", "dummy"])
    assert result.exit_code == 1
    assert "Error: Please specify either a session_id or --server, not both." in result.stdout


def test_validate_recorded_session_missing(mock_db_path: str, runner: CliRunner) -> None:
    """Verify validating a non-existent recorded session."""
    result = runner.invoke(app, ["validate", "9999"])
    assert result.exit_code == 1
    assert "Error: Session #9999 not found." in result.stdout


def test_validate_recorded_session_passing(mock_db_path: str, runner: CliRunner) -> None:
    """Verify validating a compliant recorded session."""

    async def populate() -> None:
        db = Database(db_path=mock_db_path)
        await db.connect()
        session_id = await db.create_session("dummy")
        # Initialize Request
        await db.log_message(
            session_id,
            "client_to_server",
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1.0"},
                },
            },
        )
        # Initialize Response
        await db.log_message(
            session_id,
            "server_to_client",
            {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "serverInfo": {"name": "test-server", "version": "1.0"},
                },
            },
        )
        # Initialized Notification
        await db.log_message(
            session_id,
            "client_to_server",
            {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
            },
        )
        # Tools List Request
        await db.log_message(
            session_id,
            "client_to_server",
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list",
            },
        )
        # Tools List Response
        await db.log_message(
            session_id,
            "server_to_client",
            {
                "jsonrpc": "2.0",
                "id": 2,
                "result": {"tools": []},
            },
        )
        await db.close()

    asyncio.run(populate())
    result = runner.invoke(app, ["validate", "1"])
    assert result.exit_code == 0
    assert "Overall compliance: 0 critical failures" in result.stdout
    assert "Compliance score: 100%" in result.stdout


def test_validate_recorded_session_critical_failures(mock_db_path: str, runner: CliRunner) -> None:
    """Verify validating a recorded session with critical errors."""

    async def populate() -> None:
        db = Database(db_path=mock_db_path)
        await db.connect()
        session_id = await db.create_session("dummy")
        # First request is tools/list, not initialize
        await db.log_message(
            session_id,
            "client_to_server",
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
            },
        )
        await db.close()

    asyncio.run(populate())
    result = runner.invoke(app, ["validate", "1"])
    assert result.exit_code == 1
    assert "Overall compliance: 2 critical failures" in result.stdout
    assert "Compliance score: 60%" in result.stdout


def test_validate_live_server_success(tmp_path: Any, runner: CliRunner) -> None:
    """Test live server validation with a compliant mock subprocess python script."""
    server_script = tmp_path / "mock_server.py"
    server_script.write_text(
        """
import sys
import json

def main():
    # 1. Read initialize request
    line = sys.stdin.readline()
    if not line:
        return
    req = json.loads(line)
    if req.get("method") == "initialize":
        res = {
            "jsonrpc": "2.0",
            "id": req["id"],
            "result": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "serverInfo": {"name": "mock-server", "version": "1.0.0"}
            }
        }
        sys.stdout.write(json.dumps(res) + "\\n")
        sys.stdout.flush()
    
    # 2. Read notifications/initialized
    line = sys.stdin.readline()
    if not line:
        return
    
    # 3. Read tools/list request
    line = sys.stdin.readline()
    if not line:
        return
    req2 = json.loads(line)
    if req2.get("method") == "tools/list":
        res2 = {
            "jsonrpc": "2.0",
            "id": req2["id"],
            "result": {
                "tools": [
                    {
                        "name": "greet",
                        "description": "Greet user",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"}
                            },
                            "required": ["name"]
                        }
                    }
                ]
            }
        }
        sys.stdout.write(json.dumps(res2) + "\\n")
        sys.stdout.flush()

if __name__ == "__main__":
    main()
""".strip(),
        encoding="utf-8",
    )

    cmd = f"{sys.executable} {server_script}"
    result = runner.invoke(app, ["validate", "--server", cmd])
    assert result.exit_code == 0
    assert "Overall compliance: 0 critical failures" in result.stdout
    assert "Compliance score: 100%" in result.stdout


def test_validate_live_server_timeout(tmp_path: Any, runner: CliRunner) -> None:
    """Test live server validation timing out if the server hangs."""
    server_script = tmp_path / "hanging_server.py"
    server_script.write_text(
        """
import time
time.sleep(20)
""".strip(),
        encoding="utf-8",
    )

    def mock_wait_for(coro: Any, timeout: Any) -> Any:
        coro.close()
        raise asyncio.TimeoutError()

    with patch("asyncio.wait_for", mock_wait_for):
        cmd = f"{sys.executable} {server_script}"
        result = runner.invoke(app, ["validate", "--server", cmd])
        assert result.exit_code == 1
        assert "handshake_timeout" in result.stdout


def test_validate_live_server_nonexistent(runner: CliRunner) -> None:
    """Test live server validation with nonexistent command."""
    result = runner.invoke(app, ["validate", "--server", "nonexistent_command_12345"])
    assert result.exit_code == 1
    assert "server_startup" in result.stdout or "server_connection" in result.stdout


# Live validation edge cases to achieve 100% coverage on validate_live.py
class MockStreamReader:
    def __init__(self, lines):
        self.lines = lines
        self.idx = 0

    async def readline(self):
        if self.idx >= len(self.lines):
            return b""
        val = self.lines[self.idx]
        self.idx += 1
        return val


class MockStreamWriter:
    def write(self, data):
        pass

    async def drain(self):
        pass


class MockProcess:
    def __init__(self, stdout_lines, raise_on_terminate=False):
        self.stdin = MockStreamWriter()
        self.stdout = MockStreamReader(stdout_lines)
        self.stderr = MockStreamReader([])
        self.raise_on_terminate = raise_on_terminate

    def terminate(self):
        if self.raise_on_terminate:
            raise RuntimeError("Terminate failed")

    async def wait(self):
        pass


@pytest.mark.asyncio
async def test_run_live_validation_edge_cases() -> None:
    from mcp_debugger.validate_live import run_live_validation

    # 1. DB connection fails (session_id == -1)
    with patch("mcp_debugger.storage.database.Database.create_session", return_value=-1):
        status, results = await run_live_validation("some-cmd")
        assert status == -1
        assert any(r.rule_name == "database_init" for r in results)

    # 2. Empty split command
    status, results = await run_live_validation("")
    assert any(
        r.rule_name == "server_startup" and "No valid server command" in r.message for r in results
    )

    # 3. Spawn fails with general exception
    with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError("Spawn error")):
        with patch("asyncio.create_subprocess_shell", side_effect=Exception("Shell error")):
            status, results = await run_live_validation("invalid-cmd")
            assert any(
                r.rule_name == "server_startup" and "Shell error" in r.message for r in results
            )

    # 3b. Spawn fails with general exception on create_subprocess_exec (goes to outer except)
    with patch("asyncio.create_subprocess_exec", side_effect=Exception("General spawn error")):
        status, results = await run_live_validation("invalid-cmd")
        assert any(
            r.rule_name == "server_startup" and "General spawn error" in r.message for r in results
        )

    # 4. Initialize response not received (EOF)
    mock_proc_eof = MockProcess([b"\n", b"invalid-json\n", b""])
    with patch("asyncio.create_subprocess_exec", return_value=mock_proc_eof):
        status, results = await run_live_validation("mock-cmd")
        assert any(
            r.rule_name == "server_connection" and "Connection lost" in r.message for r in results
        )

    # 4b. Initialize response not received (ID mismatch / 20 lines read but not found)
    mock_proc_mismatch = MockProcess([b'{"jsonrpc": "2.0", "id": 999, "result": {}}\n'] * 21)
    with patch("asyncio.create_subprocess_exec", return_value=mock_proc_mismatch):
        status, results = await run_live_validation("mock-cmd")
        assert any(
            r.rule_name == "server_startup" and "Initialize response not received" in r.message
            for r in results
        )

    # 5. Initialize success, but tools/list stdout closed
    mock_proc_tools_eof = MockProcess(
        [b'{"jsonrpc": "2.0", "id": 1, "result": {}}\n', b"\n", b"invalid-json\n", b""]
    )
    with patch("asyncio.create_subprocess_exec", return_value=mock_proc_tools_eof):
        status, results = await run_live_validation("mock-cmd")
        assert any(
            r.rule_name == "server_connection" and "Connection lost" in r.message for r in results
        )

    # 5b. Initialize success, but tools/list response not received (ID mismatch)
    mock_proc_tools_mismatch = MockProcess(
        [
            b'{"jsonrpc": "2.0", "id": 1, "result": {}}\n',
        ]
        + [b'{"jsonrpc": "2.0", "id": 999, "result": {}}\n'] * 21
    )
    with patch("asyncio.create_subprocess_exec", return_value=mock_proc_tools_mismatch):
        status, results = await run_live_validation("mock-cmd")
        assert any(
            r.rule_name == "server_startup" and "tools/list response not received" in r.message
            for r in results
        )

    # 6. Process termination throws exception and os.remove throws exception and validation engine fails
    mock_proc_fail = MockProcess(
        [
            b'{"jsonrpc": "2.0", "id": 1, "result": {}}\n',
            b'{"jsonrpc": "2.0", "id": 2, "result": {"tools": []}}\n',
        ],
        raise_on_terminate=True,
    )
    with patch("asyncio.create_subprocess_exec", return_value=mock_proc_fail):
        with patch("os.remove", side_effect=OSError("Remove error")):
            with patch(
                "mcp_debugger.protocol.validator.ProtocolValidator.validate_session",
                side_effect=Exception("Validate error"),
            ):
                status, results = await run_live_validation("mock-cmd")
                assert any(
                    r.rule_name == "validation_engine" and "Validate error" in r.message
                    for r in results
                )


def test_validate_dict_compatibility(runner: CliRunner, mock_db_path: str) -> None:
    """Verify validate command uses dict() fallback if model_dump is missing."""
    import json

    class LegacyValidationResult:
        def __init__(self):
            self.rule_name = "test_rule"
            self.passed = True
            self.message = "Legacy success"
            self.severity = "info"
            self.error_code = None

        def dict(self):
            return {
                "rule_name": self.rule_name,
                "passed": self.passed,
                "message": self.message,
                "severity": self.severity,
                "error_code": self.error_code,
            }

    async def populate() -> None:
        db = Database(db_path=mock_db_path)
        await db.connect()
        await db.create_session("dummy")
        await db.close()

    asyncio.run(populate())

    with patch(
        "mcp_debugger.protocol.validator.ProtocolValidator.validate_session",
        return_value=[LegacyValidationResult()],
    ):
        result = runner.invoke(app, ["validate", "1", "--json"])
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert parsed[0]["rule_name"] == "test_rule"
        assert parsed[0]["message"] == "Legacy success"
