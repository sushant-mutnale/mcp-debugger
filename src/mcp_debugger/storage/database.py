"""Asynchronous SQLite storage layer for the MCP Debugger."""

import json
import logging
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import aiosqlite

logger = logging.getLogger("mcp_debugger.storage")


class Database:
    """Handles SQLite database interactions using aiosqlite."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        """Initialize database file path and directory structure."""
        if db_path is None:
            home_dir = Path.home() / ".mcp-debugger"
            home_dir.mkdir(parents=True, exist_ok=True)
            try:
                # Secure private directory
                os.chmod(home_dir, 0o700)
            except Exception:
                pass
            self.db_path = str(home_dir / "sessions.db")
        else:
            self.db_path = db_path

        self._conn: Optional[aiosqlite.Connection] = None

    async def connect(self) -> None:
        """Establish database connection, adjust permissions, configure WAL, and create schemas."""
        db_file = Path(self.db_path)
        db_file.parent.mkdir(parents=True, exist_ok=True)

        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row

        try:
            # Set owner read/write permissions on the db file
            os.chmod(self.db_path, 0o600)
        except Exception:
            pass

        # Configure WAL, synchronous=OFF, user_version, and foreign keys
        await self._conn.execute("PRAGMA journal_mode=WAL;")
        await self._conn.execute("PRAGMA synchronous=OFF;")
        await self._conn.execute("PRAGMA foreign_keys=ON;")
        await self._conn.execute("PRAGMA user_version = 1;")

        await self._create_tables()

    async def close(self) -> None:
        """Close connection cleanly."""
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def _get_conn(self) -> aiosqlite.Connection:
        """Return the active connection, connecting if not already established."""
        if self._conn is None:
            await self.connect()
        assert self._conn is not None
        return self._conn

    async def _create_tables(self) -> None:
        """Create database tables and indexes if they do not exist."""
        conn = self._conn
        assert conn is not None

        # Table: sessions
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_uuid TEXT UNIQUE NOT NULL,
                friendly_name TEXT,
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

        # Migrate existing schemas: check if friendly_name column exists
        async with conn.execute("PRAGMA table_info(sessions);") as cursor:
            columns = [row[1] for row in await cursor.fetchall()]
        if columns and "friendly_name" not in columns:
            await conn.execute("ALTER TABLE sessions ADD COLUMN friendly_name TEXT;")
            await conn.commit()

        # Table: messages
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                message_id TEXT,
                direction TEXT NOT NULL CHECK(direction IN ('client_to_server', 'server_to_client')),
                method TEXT,
                params TEXT,
                result TEXT,
                error TEXT,
                timestamp REAL NOT NULL,
                latency_ms REAL,
                message_type TEXT CHECK(message_type IN ('request', 'response', 'notification'))
            );
            """
        )

        # Table: tools
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tools (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                description TEXT,
                input_schema TEXT NOT NULL,
                output_schema TEXT,
                first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(session_id, name)
            );
            """
        )

        # Table: errors
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS errors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                message_id INTEGER REFERENCES messages(id) ON DELETE SET NULL,
                error_code INTEGER,
                error_type TEXT,
                error_message TEXT,
                stack_trace TEXT,
                classified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )

        # Indexes
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id);"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp);"
        )
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_method ON messages(method);")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_tools_session_id ON tools(session_id);")
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_errors_session_id ON errors(session_id);"
        )

        await conn.commit()

    async def create_session(
        self,
        server_command: str,
        client_info: Optional[str] = None,
        server_name: Optional[str] = None,
        friendly_name: Optional[str] = None,
    ) -> int:
        """Create a new debugging session record, returning its integer ID."""
        try:
            conn = await self._get_conn()
            session_uuid = str(uuid.uuid4())
            async with conn.execute(
                """
                INSERT INTO sessions (session_uuid, friendly_name, server_command, server_name, client_info, status)
                VALUES (?, ?, ?, ?, ?, 'running')
                """,
                (session_uuid, friendly_name, server_command, server_name, client_info),
            ) as cursor:
                session_id = cursor.lastrowid
            await conn.commit()
            return session_id if session_id is not None else -1
        except Exception as e:
            logger.warning("Failed to create session: %s", e)
            return -1

    async def log_message(
        self,
        session_id: int,
        direction: str,
        message: Union[Dict[str, Any], Any],
    ) -> int:
        """Log a validated Pydantic model or raw dict JSON-RPC message into storage."""
        try:
            if hasattr(message, "model_dump"):
                msg_dict = message.model_dump()
            else:
                msg_dict = dict(message)

            conn = await self._get_conn()

            msg_id = msg_dict.get("id")
            msg_id_str = str(msg_id) if msg_id is not None else None

            method = msg_dict.get("method")
            params = (
                json.dumps(msg_dict.get("params"))
                if "params" in msg_dict and msg_dict["params"] is not None
                else None
            )
            result = (
                json.dumps(msg_dict.get("result"))
                if "result" in msg_dict and msg_dict["result"] is not None
                else None
            )
            error = (
                json.dumps(msg_dict.get("error"))
                if "error" in msg_dict and msg_dict["error"] is not None
                else None
            )

            # Determine type
            if msg_id_str is not None:
                if method is not None:
                    message_type = "request"
                else:
                    message_type = "response"
            else:
                message_type = "notification"

            timestamp = time.time() * 1000.0
            latency_ms = None

            # Calculate response latency and match methods
            if message_type == "response" and msg_id_str is not None:
                async with conn.execute(
                    """
                    SELECT timestamp, method FROM messages
                    WHERE session_id = ? AND message_id = ? AND message_type = 'request'
                    ORDER BY timestamp DESC LIMIT 1
                    """,
                    (session_id, msg_id_str),
                ) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        req_timestamp = row[0]
                        method = row[1]
                        latency_ms = timestamp - req_timestamp

            # Insert message
            async with conn.execute(
                """
                INSERT INTO messages (
                    session_id, message_id, direction, method, params, result, error,
                    timestamp, latency_ms, message_type
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    msg_id_str,
                    direction,
                    method,
                    params,
                    result,
                    error,
                    timestamp,
                    latency_ms,
                    message_type,
                ),
            ) as cursor:
                inserted_id = cursor.lastrowid

            # Increment count
            await conn.execute(
                "UPDATE sessions SET total_messages = total_messages + 1 WHERE id = ?",
                (session_id,),
            )
            await conn.commit()

            return inserted_id if inserted_id is not None else -1
        except Exception as e:
            logger.warning("Failed to log message: %s", e)
            return -1

    async def log_tool(self, session_id: int, tool: Union[Dict[str, Any], Any]) -> None:
        """Log a tool definition discovered in tools/list response."""
        try:
            if hasattr(tool, "model_dump"):
                tool_dict = tool.model_dump()
            else:
                tool_dict = dict(tool)

            conn = await self._get_conn()
            name = tool_dict.get("name")
            description = tool_dict.get("description")
            input_schema = json.dumps(
                tool_dict.get("inputSchema") or tool_dict.get("input_schema") or {}
            )
            output_schema = (
                json.dumps(tool_dict.get("outputSchema") or tool_dict.get("output_schema"))
                if "outputSchema" in tool_dict or "output_schema" in tool_dict
                else None
            )

            async with conn.execute(
                """
                INSERT OR IGNORE INTO tools (session_id, name, description, input_schema, output_schema)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, name, description, input_schema, output_schema),
            ) as cursor:
                changes = cursor.rowcount

            if changes > 0:
                await conn.execute(
                    "UPDATE sessions SET total_tools_discovered = total_tools_discovered + 1 WHERE id = ?",
                    (session_id,),
                )
            await conn.commit()
        except Exception as e:
            logger.warning("Failed to log tool: %s", e)

    async def log_error(
        self,
        session_id: int,
        error_code: int,
        error_type: str,
        error_message: str,
        message_id: Optional[int] = None,
        stack_trace: Optional[str] = None,
    ) -> None:
        """Store classified protocol or execution errors."""
        try:
            conn = await self._get_conn()
            await conn.execute(
                """
                INSERT INTO errors (session_id, message_id, error_code, error_type, error_message, stack_trace)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (session_id, message_id, error_code, error_type, error_message, stack_trace),
            )
            await conn.execute(
                "UPDATE sessions SET total_errors = total_errors + 1 WHERE id = ?",
                (session_id,),
            )
            await conn.commit()
        except Exception as e:
            logger.warning("Failed to log error: %s", e)

    async def close_session(self, session_id: int, status: str) -> None:
        """Mark a session as completed or errored, updating ended_at timestamps."""
        try:
            conn = await self._get_conn()
            await conn.execute(
                """
                UPDATE sessions
                SET ended_at = CURRENT_TIMESTAMP, status = ?
                WHERE id = ?
                """,
                (status, session_id),
            )
            await conn.commit()
        except Exception as e:
            logger.warning("Failed to close session: %s", e)

    async def get_session(self, session_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve details of a specific session."""
        try:
            conn = await self._get_conn()
            async with conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.warning("Failed to get session: %s", e)
            return None

    async def get_messages(
        self,
        session_id: int,
        method: Optional[str] = None,
        direction: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Query and return logged messages, optionally filtering by method and direction."""
        try:
            conn = await self._get_conn()
            query = "SELECT * FROM messages WHERE session_id = ?"
            params: List[Any] = [session_id]

            if method is not None:
                query += " AND method = ?"
                params.append(method)

            if direction is not None:
                query += " AND direction = ?"
                params.append(direction)

            query += " ORDER BY timestamp ASC"

            if limit is not None:
                query += " LIMIT ?"
                params.append(limit)

            async with conn.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.warning("Failed to get messages: %s", e)
            return []

    async def get_tools(self, session_id: int) -> List[Dict[str, Any]]:
        """Retrieve all unique tools discovered in a session."""
        try:
            conn = await self._get_conn()
            async with conn.execute(
                "SELECT * FROM tools WHERE session_id = ? ORDER BY first_seen_at ASC",
                (session_id,),
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.warning("Failed to get tools: %s", e)
            return []

    async def get_errors(self, session_id: int) -> List[Dict[str, Any]]:
        """Retrieve all errors logged in a session."""
        try:
            conn = await self._get_conn()
            async with conn.execute(
                "SELECT * FROM errors WHERE session_id = ? ORDER BY classified_at ASC",
                (session_id,),
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.warning("Failed to get errors: %s", e)
            return []

    async def get_sessions(
        self,
        limit: int = 20,
        status_filter: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Retrieve historical debugging sessions in reverse chronological order."""
        try:
            conn = await self._get_conn()
            query = """
                SELECT 
                    id,
                    session_uuid,
                    friendly_name,
                    server_command,
                    server_name,
                    started_at,
                    ended_at,
                    status,
                    total_messages,
                    total_tools_discovered,
                    total_errors,
                    (CAST(strftime('%s', COALESCE(ended_at, CURRENT_TIMESTAMP)) AS INTEGER) - CAST(strftime('%s', started_at) AS INTEGER)) AS duration_seconds
                FROM sessions
            """
            params: List[Any] = []
            if status_filter is not None:
                query += " WHERE status = ?"
                params.append(status_filter)

            query += " ORDER BY started_at DESC, id DESC LIMIT ?"
            params.append(limit)

            async with conn.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.warning("Failed to get sessions: %s", e)
            return []
