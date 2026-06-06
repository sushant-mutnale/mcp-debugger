"""Tests for the SQLite storage layer using aiosqlite."""

import os
import tempfile
import time
from typing import Any, AsyncGenerator
import pytest
import sqlite3

from mcp_debugger.protocol.schemas import JSONRPCRequest
from mcp_debugger.storage.database import Database


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


async def test_database_initialization(temp_db: Database) -> None:
    """Verify that tables, indices, and configurations (WAL, foreign keys) are set up."""
    # Check that file exists
    assert os.path.exists(temp_db.db_path)

    # Check WAL mode
    conn = await temp_db._get_conn()
    async with conn.execute("PRAGMA journal_mode;") as cursor:
        row = await cursor.fetchone()
        assert row is not None
        assert row[0].lower() == "wal"

    # Check foreign keys
    async with conn.execute("PRAGMA foreign_keys;") as cursor:
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == 1

    # Check schemas version
    async with conn.execute("PRAGMA user_version;") as cursor:
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == 1

    # Check permissions (on non-Windows platforms)
    if os.name != "nt":
        stat = os.stat(temp_db.db_path)
        # Verify permissions are owner read/write (0o600)
        assert (stat.st_mode & 0o777) == 0o600


async def test_create_session(temp_db: Database) -> None:
    """Verify that create_session creates new session record correctly."""
    session_id1 = await temp_db.create_session(
        server_command="npx -y mock-server",
        client_info='{"client": "test"}',
        server_name="mock-server",
    )
    assert session_id1 == 1

    session_id2 = await temp_db.create_session(
        server_command="python -m my_server",
    )
    assert session_id2 == 2

    # Fetch and check details
    session = await temp_db.get_session(session_id1)
    assert session is not None
    assert session["id"] == 1
    assert session["server_command"] == "npx -y mock-server"
    assert session["server_name"] == "mock-server"
    assert session["client_info"] == '{"client": "test"}'
    assert session["status"] == "running"
    assert session["session_uuid"] is not None
    assert session["started_at"] is not None
    assert session["ended_at"] is None
    assert session["total_messages"] == 0
    assert session["total_tools_discovered"] == 0
    assert session["total_errors"] == 0


async def test_log_message_request_and_response(temp_db: Database) -> None:
    """Verify message logging, type classification, and latency computation."""
    session_id = await temp_db.create_session(server_command="dummy")

    # 1. Log a Request message (using Pydantic model)
    req_model = JSONRPCRequest(
        jsonrpc="2.0",
        id="msg-101",
        method="tools/call",
        params={"name": "test_tool", "arguments": {}},
    )
    req_id = await temp_db.log_message(
        session_id=session_id, direction="client_to_server", message=req_model
    )
    assert req_id > 0

    # Wait briefly to ensure non-zero latency delta
    time.sleep(0.01)

    # 2. Log matching Response message
    resp_dict = {
        "jsonrpc": "2.0",
        "id": "msg-101",
        "result": {"content": [{"type": "text", "text": "success"}]},
    }
    resp_id = await temp_db.log_message(
        session_id=session_id, direction="server_to_client", message=resp_dict
    )
    assert resp_id > 0

    # Query logged messages
    messages = await temp_db.get_messages(session_id)
    assert len(messages) == 2

    req_row = messages[0]
    assert req_row["message_id"] == "msg-101"
    assert req_row["direction"] == "client_to_server"
    assert req_row["method"] == "tools/call"
    assert req_row["message_type"] == "request"
    assert req_row["latency_ms"] is None

    resp_row = messages[1]
    assert resp_row["message_id"] == "msg-101"
    assert resp_row["direction"] == "server_to_client"
    assert resp_row["method"] == "tools/call"  # Copied from request
    assert resp_row["message_type"] == "response"
    assert resp_row["latency_ms"] is not None
    assert resp_row["latency_ms"] > 0

    # Check session totals update
    session = await temp_db.get_session(session_id)
    assert session is not None
    assert session["total_messages"] == 2


async def test_log_notification(temp_db: Database) -> None:
    """Verify log_message correctly parses JSON-RPC notification type (no ID)."""
    session_id = await temp_db.create_session(server_command="dummy")

    notif_dict = {
        "jsonrpc": "2.0",
        "method": "notifications/initialized",
        "params": {"ready": True},
    }
    notif_id = await temp_db.log_message(
        session_id=session_id, direction="client_to_server", message=notif_dict
    )
    assert notif_id > 0

    messages = await temp_db.get_messages(session_id)
    assert len(messages) == 1
    assert messages[0]["message_id"] is None
    assert messages[0]["method"] == "notifications/initialized"
    assert messages[0]["message_type"] == "notification"


async def test_log_tool_ignoring_duplicates(temp_db: Database) -> None:
    """Verify tool definitions are logged, and duplicates within the same session are ignored."""
    session_id = await temp_db.create_session(server_command="dummy")

    class MockPydanticTool:
        def model_dump(self) -> dict[str, Any]:
            return {
                "name": "calculate_sum",
                "description": "Sum up two integers",
                "inputSchema": {"type": "object"},
            }

    tool = MockPydanticTool()

    # First insert
    await temp_db.log_tool(session_id, tool)
    tools = await temp_db.get_tools(session_id)
    assert len(tools) == 1
    assert tools[0]["name"] == "calculate_sum"

    session = await temp_db.get_session(session_id)
    assert session is not None
    assert session["total_tools_discovered"] == 1

    # Second insert of the same tool (should ignore and not increment count)
    await temp_db.log_tool(session_id, tool)
    tools = await temp_db.get_tools(session_id)
    assert len(tools) == 1

    session = await temp_db.get_session(session_id)
    assert session is not None
    assert session["total_tools_discovered"] == 1


async def test_log_error(temp_db: Database) -> None:
    """Verify error logging and total_errors updates."""
    session_id = await temp_db.create_session(server_command="dummy")

    await temp_db.log_error(
        session_id=session_id,
        error_code=-32601,
        error_type="protocol",
        error_message="Method not found",
        stack_trace="Traceback info...",
    )

    errors = await temp_db.get_errors(session_id)
    assert len(errors) == 1
    assert errors[0]["error_code"] == -32601
    assert errors[0]["error_type"] == "protocol"
    assert errors[0]["error_message"] == "Method not found"
    assert errors[0]["stack_trace"] == "Traceback info..."

    session = await temp_db.get_session(session_id)
    assert session is not None
    assert session["total_errors"] == 1


async def test_close_session(temp_db: Database) -> None:
    """Verify that close_session updates status and ended_at time."""
    session_id = await temp_db.create_session(server_command="dummy")

    await temp_db.close_session(session_id, status="completed")

    session = await temp_db.get_session(session_id)
    assert session is not None
    assert session["status"] == "completed"
    assert session["ended_at"] is not None


async def test_get_messages_filters(temp_db: Database) -> None:
    """Verify filtering messages by method, direction, and limits."""
    session_id = await temp_db.create_session(server_command="dummy")

    # Log 3 messages
    await temp_db.log_message(
        session_id, "client_to_server", {"jsonrpc": "2.0", "id": 1, "method": "methodA"}
    )
    await temp_db.log_message(
        session_id, "server_to_client", {"jsonrpc": "2.0", "id": 2, "method": "methodB"}
    )
    await temp_db.log_message(
        session_id, "client_to_server", {"jsonrpc": "2.0", "id": 3, "method": "methodA"}
    )

    # Filter by method
    res = await temp_db.get_messages(session_id, method="methodA")
    assert len(res) == 2
    assert res[0]["method"] == "methodA"
    assert res[1]["method"] == "methodA"

    # Filter by direction
    res = await temp_db.get_messages(session_id, direction="server_to_client")
    assert len(res) == 1
    assert res[0]["method"] == "methodB"

    # Filter by limit
    res = await temp_db.get_messages(session_id, limit=2)
    assert len(res) == 2


async def test_get_messages_search_and_offset(temp_db: Database) -> None:
    """Verify filtering messages by search text and offset/pagination."""
    session_id = await temp_db.create_session(server_command="dummy")

    # Log messages with different JSON fields
    await temp_db.log_message(
        session_id,
        "client_to_server",
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "test_tool", "value": "apple"},
        },
    )
    await temp_db.log_message(
        session_id,
        "server_to_client",
        {"jsonrpc": "2.0", "id": 1, "result": {"data": "banana cherry"}},
    )
    await temp_db.log_message(
        session_id,
        "server_to_client",
        {"jsonrpc": "2.0", "id": 2, "error": {"code": -32000, "message": "durian error"}},
    )

    # 1. Search in params
    res = await temp_db.get_messages(session_id, search="apple")
    assert len(res) == 1
    assert res[0]["method"] == "tools/call"

    # 2. Search in result
    res = await temp_db.get_messages(session_id, search="banana")
    assert len(res) == 1
    assert "cherry" in res[0]["result"]

    # 3. Search in error
    res = await temp_db.get_messages(session_id, search="durian")
    assert len(res) == 1
    assert "durian" in res[0]["error"]

    # 4. Search no match
    res = await temp_db.get_messages(session_id, search="grape")
    assert len(res) == 0

    # 5. Offset only
    res = await temp_db.get_messages(session_id, offset=1)
    assert len(res) == 2
    assert res[0]["id"] == 2  # second message
    assert res[1]["id"] == 3  # third message

    # 6. Limit and offset
    res = await temp_db.get_messages(session_id, limit=1, offset=1)
    assert len(res) == 1
    assert res[0]["id"] == 2


async def test_robust_error_handling(temp_db: Database) -> None:
    """Verify that constraints violations or invalid database handles do not crash code."""
    # Attempt message insertion into non-existent session_id (violating foreign key constraint)
    msg_id = await temp_db.log_message(
        session_id=99999,
        direction="client_to_server",
        message={"jsonrpc": "2.0", "id": 1, "method": "hello"},
    )
    # Check that it returns -1 instead of throwing exception
    assert msg_id == -1

    # Test error logging into non-existent session
    await temp_db.log_error(
        session_id=99999,
        error_code=-1,
        error_type="testing",
        error_message="testing constraint failure",
    )
    # Should complete without error and list should be empty
    errors = await temp_db.get_errors(99999)
    assert len(errors) == 0


async def test_performance_1000_message_inserts(temp_db: Database) -> None:
    """Verify that 1000 message inserts take less than 0.5 seconds with optimizations."""
    session_id = await temp_db.create_session(server_command="perf_test")

    start_time = time.perf_counter()
    for i in range(1000):
        await temp_db.log_message(
            session_id=session_id,
            direction="client_to_server",
            message={"jsonrpc": "2.0", "id": i, "method": "perf_test"},
        )
    end_time = time.perf_counter()
    duration = end_time - start_time

    assert duration < 0.5


async def test_default_db_path() -> None:
    """Verify that the database can be initialized with the default path."""
    db = Database(db_path=None)
    assert ".mcp-debugger" in db.db_path
    await db.connect()
    session_id = await db.create_session(server_command="test_default")
    assert session_id > 0
    await db.close()


async def test_database_exceptions(temp_db: Database) -> None:
    """Verify that exceptions in database operations are handled gracefully."""
    await temp_db.close()

    class FakeConn:
        def execute(self, *args: Any, **kwargs: Any) -> Any:
            class FakeCursor:
                async def __aenter__(self) -> Any:
                    raise sqlite3.Error("Mocked database error")

                async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
                    pass

            return FakeCursor()

        async def commit(self) -> None:
            raise sqlite3.Error("Mocked database error")

        async def close(self) -> None:
            pass

    temp_db._conn = FakeConn()  # type: ignore

    session_id = await temp_db.create_session("dummy")
    assert session_id == -1

    msg_id = await temp_db.log_message(1, "client_to_server", {})
    assert msg_id == -1

    await temp_db.log_tool(1, {"name": "test"})
    await temp_db.log_error(1, -1, "test", "test")
    await temp_db.close_session(1, "completed")

    assert await temp_db.get_session(1) is None
    assert await temp_db.get_messages(1) == []
    assert await temp_db.get_tools(1) == []
    assert await temp_db.get_errors(1) == []


async def test_schema_migration_friendly_name() -> None:
    """Verify that old schemas are automatically migrated to add the friendly_name column."""
    import aiosqlite

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    # Initialize a database with the old schema (no friendly_name)
    async with aiosqlite.connect(path) as conn:
        await conn.execute(
            """
            CREATE TABLE sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_uuid TEXT UNIQUE NOT NULL,
                server_command TEXT NOT NULL,
                server_name TEXT,
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ended_at TIMESTAMP,
                status TEXT DEFAULT 'running',
                client_info TEXT,
                server_info TEXT,
                protocol_version TEXT,
                total_messages INTEGER DEFAULT 0,
                total_tools_discovered INTEGER DEFAULT 0,
                total_errors INTEGER DEFAULT 0
            );
            """
        )
        # Add a dummy session
        await conn.execute(
            "INSERT INTO sessions (session_uuid, server_command) VALUES ('uuid-123', 'old-command')"
        )
        await conn.commit()

    # Now open with Database manager
    db = Database(db_path=path)
    await db.connect()

    # Verify column exists and has been migrated
    session = await db.get_session(1)
    assert session is not None
    assert "friendly_name" in session
    assert session["friendly_name"] is None

    # Verify we can write to it
    new_session_id = await db.create_session(
        server_command="new-command", friendly_name="my-friendly-name"
    )
    assert new_session_id > 0
    new_session = await db.get_session(new_session_id)
    assert new_session is not None
    assert new_session["friendly_name"] == "my-friendly-name"

    await db.close()
    try:
        os.remove(path)
    except Exception:
        pass


async def test_get_sessions_list(temp_db: Database) -> None:
    """Verify get_sessions functionality, ordering, limits, and status filtering."""
    # Create 3 sessions
    s1 = await temp_db.create_session("server-1", friendly_name="name-1")
    s2 = await temp_db.create_session("server-2", friendly_name="name-2")
    s3 = await temp_db.create_session("server-3", friendly_name="name-3")

    await temp_db.close_session(s1, "completed")
    await temp_db.close_session(s2, "error")
    # s3 remains running

    # Test reverse chronological order (s3 is newest)
    sessions = await temp_db.get_sessions(limit=10)
    assert len(sessions) == 3
    assert sessions[0]["id"] == s3
    assert sessions[0]["friendly_name"] == "name-3"
    assert sessions[0]["status"] == "running"
    assert sessions[1]["id"] == s2
    assert sessions[2]["id"] == s1

    # Test limit
    limited_sessions = await temp_db.get_sessions(limit=2)
    assert len(limited_sessions) == 2
    assert limited_sessions[0]["id"] == s3

    # Test status filter
    completed_sessions = await temp_db.get_sessions(status_filter="completed")
    assert len(completed_sessions) == 1
    assert completed_sessions[0]["id"] == s1

    error_sessions = await temp_db.get_sessions(status_filter="error")
    assert len(error_sessions) == 1
    assert error_sessions[0]["id"] == s2

    # Verify duration calculations
    assert sessions[0]["duration_seconds"] >= 0
