"""Unit tests for mcp-debugger ci CLI command."""

import asyncio
import json
from typer.testing import CliRunner

from mcp_debugger.cli import app
from mcp_debugger.storage.database import Database


def test_ci_missing_session(mock_db_path: str, runner: CliRunner) -> None:
    """Verify ci command fails when session does not exist."""
    result = runner.invoke(app, ["ci", "9999"])
    assert result.exit_code == 1
    assert "not found" in result.stdout.lower()


def test_ci_clean_session_passes(mock_db_path: str, runner: CliRunner) -> None:
    """Verify ci command passes on a valid compliant session."""

    async def setup_clean() -> int:
        db = Database(db_path=mock_db_path)
        await db.connect()
        sid = await db.create_session("clean-ci-session")

        # Step 0: valid initialize request
        await db.log_message(
            sid,
            "client_to_server",
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "test-client", "version": "1.0"},
                },
            },
        )

        # Step 1: valid initialize response
        await db.log_message(
            sid,
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

        await db.log_message(
            sid,
            "client_to_server",
            {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
            },
        )

        await db.close()
        return sid

    sid = asyncio.run(setup_clean())

    result = runner.invoke(app, ["ci", str(sid)])
    assert result.exit_code == 0
    assert "PASSED" in result.stdout


def test_ci_protocol_violation_fails(mock_db_path: str, runner: CliRunner) -> None:
    """Verify ci command exits with 1 when protocol schema violations are present."""

    async def setup_bad_proto() -> int:
        db = Database(db_path=mock_db_path)
        await db.connect()
        sid = await db.create_session("bad-proto-session")

        # Invalid call before initialize (critical protocol error)
        await db.log_message(
            sid,
            "client_to_server",
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
            },
        )

        await db.close()
        return sid

    sid = asyncio.run(setup_bad_proto())

    result = runner.invoke(app, ["ci", str(sid)])
    assert result.exit_code == 1
    assert "FAILED" in result.stdout


def test_ci_replay_mismatch_fails(mock_db_path: str, runner: CliRunner) -> None:
    """Verify ci command fails when session has replay regression mismatches."""

    async def setup_replay_failure() -> int:
        db = Database(db_path=mock_db_path)
        await db.connect()
        sid = await db.create_session("replay-fail-session")

        mid = await db.log_message(
            sid,
            "client_to_server",
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "test-client", "version": "1.0"},
                },
            },
        )
        await db.log_message(
            sid,
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

        # Log a failed replay record
        await db.save_replay(
            source_session_id=sid,
            target_server_command="test-server",
            status="completed",
            total_messages=1,
            mismatches=1,
            messages=[{
                "original_message_id": mid,
                "original_response": {"result": "a"},
                "replayed_response": {"result": "b"},
                "matches": False,
                "error": "Output divergence",
                "latency_ms": 10.0,
            }],
            started_at="2026-11-22 00:00:00",
            ended_at="2026-11-22 00:00:01",
        )

        await db.close()
        return sid

    sid = asyncio.run(setup_replay_failure())

    result = runner.invoke(app, ["ci", str(sid)])
    assert result.exit_code == 1
    assert "FAILED" in result.stdout


def test_ci_warning_latency_threshold(mock_db_path: str, runner: CliRunner) -> None:
    """Verify latency threshold emits warning (exit 0 without --strict, exit 1 with --strict)."""

    async def setup_slow_session() -> int:
        db = Database(db_path=mock_db_path)
        await db.connect()
        sid = await db.create_session("slow-session")

        await db.log_message(
            sid,
            "client_to_server",
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "slow", "version": "1.0"},
                },
            },
        )
        await db.log_message(
            sid,
            "server_to_client",
            {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "serverInfo": {"name": "slow", "version": "1.0"},
                },
            },
        )
        await db.log_message(
            sid,
            "client_to_server",
            {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
            },
        )

        # Set high latency on the message row
        conn = await db._get_conn()
        await conn.execute("UPDATE messages SET latency_ms = 250.0 WHERE session_id = ?", (sid,))
        await conn.commit()

        await db.close()
        return sid

    sid = asyncio.run(setup_slow_session())

    # Without --strict: Non-blocking warning -> Exit 0
    res_normal = runner.invoke(app, ["ci", str(sid), "--max-latency", "50"])
    assert res_normal.exit_code == 0
    assert "PASSED" in res_normal.stdout

    # With --strict: Warning becomes failure -> Exit 1
    res_strict = runner.invoke(app, ["ci", str(sid), "--max-latency", "50", "--strict"])
    assert res_strict.exit_code == 1
    assert "FAILED" in res_strict.stdout


def test_ci_json_mode(mock_db_path: str, runner: CliRunner) -> None:
    """Verify ci command structured JSON output."""

    async def setup_session() -> int:
        db = Database(db_path=mock_db_path)
        await db.connect()
        sid = await db.create_session("json-ci-session")

        await db.log_message(
            sid,
            "client_to_server",
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "c", "version": "1.0"},
                },
            },
        )
        await db.log_message(
            sid,
            "server_to_client",
            {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "serverInfo": {"name": "s", "version": "1.0"},
                },
            },
        )
        await db.log_message(
            sid,
            "client_to_server",
            {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
            },
        )

        await db.close()
        return sid

    sid = asyncio.run(setup_session())

    result = runner.invoke(app, ["ci", str(sid), "--json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["gate_passed"] is True
    assert data["exit_code"] == 0
    assert len(data["sessions"]) == 1
    assert data["sessions"][0]["session_id"] == sid
    assert data["sessions"][0]["status"] == "PASSED"
