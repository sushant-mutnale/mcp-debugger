"""Asynchronous SQLite storage layer for the MCP Debugger."""

import asyncio
import json
import logging
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple, Union
import aiosqlite

logger = logging.getLogger("mcp_debugger.storage")


class Database:
    """Handles SQLite database interactions using aiosqlite."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        """Initialize database file path and directory structure."""
        if db_path is None:
            db_path = os.environ.get("MCP_DEBUGGER_DATABASE_PATH")

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

        # Batch-write buffer: rows waiting to be INSERTed into messages
        self._write_queue: asyncio.Queue[Optional[Tuple[Any, ...]]] = asyncio.Queue()
        self._flush_task: Optional[asyncio.Task[None]] = None
        # Flush when buffer reaches this size OR after this many seconds
        self._flush_batch_size: int = 100
        self._flush_interval: float = 0.5

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
        """Flush pending writes, stop background task, then close connection cleanly."""
        await self.stop_flush_task()
        if self._conn:
            await self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # Batch-write machinery
    # ------------------------------------------------------------------

    def start_flush_task(self) -> None:
        """Launch background coroutine that drains the write queue periodically.

        Call this once after connect() when you expect high-throughput writes
        (e.g. from the proxy). Safe to call multiple times – a second call is
        a no-op if the task is already running.
        """
        if self._flush_task is None or self._flush_task.done():
            self._flush_task = asyncio.create_task(self._flush_loop())

    async def stop_flush_task(self) -> None:
        """Signal the flush loop to finish, drain remaining items, and await completion."""
        if self._flush_task and not self._flush_task.done():
            # Sentinel: None tells the loop to exit after draining
            await self._write_queue.put(None)

            # Wait up to 5 seconds for the task to finish without using nested asyncio.wait_for
            import time
            start_wait = time.perf_counter()
            while not self._flush_task.done() and (time.perf_counter() - start_wait) < 5.0:
                await asyncio.sleep(0.05)

            if not self._flush_task.done():
                self._flush_task.cancel()
                try:
                    await self._flush_task
                except (asyncio.CancelledError, TypeError):
                    pass
        self._flush_task = None
        # Drain any remaining items synchronously
        await self._drain_queue()

    async def flush(self) -> None:
        """Immediately drain all queued writes to disk. Call before close()."""
        await self._drain_queue()

    async def _flush_loop(self) -> None:
        """Background loop: flush every _flush_interval seconds or every _flush_batch_size rows."""
        batch: List[Tuple[Any, ...]] = []
        while True:
            try:
                item = await asyncio.wait_for(self._write_queue.get(), timeout=self._flush_interval)
                if item is None:  # sentinel – exit after draining
                    if batch:
                        await self._commit_batch(batch)
                    break
                batch.append(item)
                if len(batch) >= self._flush_batch_size:
                    await self._commit_batch(batch)
                    batch = []
            except asyncio.TimeoutError:
                if batch:
                    await self._commit_batch(batch)
                    batch = []

    async def _drain_queue(self) -> None:
        """Drain all currently queued rows in one batch commit (blocking)."""
        batch: List[Tuple[Any, ...]] = []
        while not self._write_queue.empty():
            item = self._write_queue.get_nowait()
            if item is None:
                break
            batch.append(item)
        if batch:
            await self._commit_batch(batch)

    async def _commit_batch(self, batch: List[Tuple[Any, ...]]) -> None:
        """Write a list of message rows with a single executemany + commit."""
        if not batch:
            return
        try:
            conn = await self._get_conn()
            await conn.executemany(
                """
                INSERT INTO messages (
                    session_id, message_id, direction, method, params, result, error,
                    timestamp, latency_ms, message_type
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                batch,
            )
            # Update session total_messages in bulk
            # Group by session_id to avoid N UPDATE calls
            counts: Dict[int, int] = {}
            for row in batch:
                sid = int(row[0])
                counts[sid] = counts.get(sid, 0) + 1
            for sid, cnt in counts.items():
                await conn.execute(
                    "UPDATE sessions SET total_messages = total_messages + ? WHERE id = ?",
                    (cnt, sid),
                )
            await conn.commit()
        except Exception as e:
            logger.warning("Batch commit failed (%d rows): %s", len(batch), e)

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
                suggestion TEXT,
                stack_trace TEXT,
                classified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )

        # Migrate errors table to include suggestion if missing
        async with conn.execute("PRAGMA table_info(errors);") as cursor:
            errors_columns = [row[1] for row in await cursor.fetchall()]
        if errors_columns and "suggestion" not in errors_columns:
            await conn.execute("ALTER TABLE errors ADD COLUMN suggestion TEXT;")
            await conn.commit()

        # Table: server_logs – raw non-JSON lines written by server to stdout
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS server_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                source TEXT NOT NULL DEFAULT 'server_stdout',
                raw_text TEXT NOT NULL,
                logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_server_logs_session_id ON server_logs(session_id);"
        )

        # Table: replays
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS replays (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                target_server_command TEXT NOT NULL,
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ended_at TIMESTAMP,
                status TEXT,
                total_messages INTEGER,
                mismatches INTEGER
            );
            """
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_replays_session_id ON replays(source_session_id);"
        )

        # Table: replay_messages
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS replay_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                replay_id INTEGER NOT NULL REFERENCES replays(id) ON DELETE CASCADE,
                original_message_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
                original_response_json TEXT,
                replayed_response_json TEXT,
                matches BOOLEAN,
                error TEXT,
                latency_ms REAL
            );
            """
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_replay_messages_replay_id ON replay_messages(replay_id);"
        )

        # ---- Indexes --------------------------------------------------------
        # Composite indexes that cover the hot query patterns:
        #   get_messages: WHERE session_id=? ORDER BY timestamp ASC
        #   get_replay_messages: WHERE session_id=? AND direction=? ORDER BY timestamp ASC
        #   get_messages(method=?): WHERE session_id=? AND method=?
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_session_ts ON messages(session_id, timestamp);"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_session_method "
            "ON messages(session_id, method);"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_session_direction "
            "ON messages(session_id, direction, timestamp);"
        )
        # Keep legacy single-column indexes for backwards compat with older DBs
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id);"
        )
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
        """Log a JSON-RPC message.

        If the flush task is running (high-throughput proxy mode) the row is
        placed on the write queue and -1 is returned (no inserted ID yet).
        If the flush task is NOT running the write is committed immediately so
        that callers that need the inserted ID (e.g. tests, replay engine) still
        work correctly.
        """
        try:
            if hasattr(message, "model_dump"):
                msg_dict = message.model_dump()
            else:
                msg_dict = dict(message)

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
            latency_ms: Optional[float] = None

            # Calculate response latency – needs a DB read so always synchronous.
            if message_type == "response" and msg_id_str is not None:
                conn = await self._get_conn()
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

            row_tuple: Tuple[Any, ...] = (
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
            )

            # Batch path: only queue *notifications* — they are the high-volume
            # messages and have no ordering dependencies with other messages.
            # Requests must be committed synchronously so the matching response
            # can find them via SELECT. Responses must also be synchronous
            # because they need latency data from the request row.
            if (
                message_type == "notification"
                and self._flush_task is not None
                and not self._flush_task.done()
            ):
                self._write_queue.put_nowait(row_tuple)
                return -1

            # Synchronous path: direct INSERT + commit (requests, responses, fallback)
            conn = await self._get_conn()
            async with conn.execute(
                """
                INSERT INTO messages (
                    session_id, message_id, direction, method, params, result, error,
                    timestamp, latency_ms, message_type
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                row_tuple,
            ) as cursor:
                inserted_id = cursor.lastrowid

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
        message_id: Optional[int] = None,
        error_type: str = "unknown",
        error_message: str = "",
        suggestion: Optional[str] = None,
        error_code: Optional[int] = None,
        stack_trace: Optional[str] = None,
    ) -> int:
        """Store classified protocol or execution errors."""
        try:
            conn = await self._get_conn()
            async with conn.execute(
                """
                INSERT INTO errors (session_id, message_id, error_code, error_type, error_message, suggestion, stack_trace)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    message_id,
                    error_code,
                    error_type,
                    error_message,
                    suggestion,
                    stack_trace,
                ),
            ) as cursor:
                inserted_id = cursor.lastrowid
            await conn.execute(
                "UPDATE sessions SET total_errors = total_errors + 1 WHERE id = ?",
                (session_id,),
            )
            await conn.commit()
            return inserted_id if inserted_id is not None else -1
        except Exception as e:
            logger.warning("Failed to log error: %s", e)
            return -1

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

    async def log_raw_line(
        self,
        session_id: int,
        raw_text: str,
        source: str = "server_stdout",
    ) -> None:
        """Store a raw non-JSON line (e.g. a server debug log) in the server_logs table."""
        try:
            conn = await self._get_conn()
            await conn.execute(
                "INSERT INTO server_logs (session_id, source, raw_text) VALUES (?, ?, ?)",
                (session_id, source, raw_text[:4096]),  # cap at 4 KB
            )
            await conn.commit()
        except Exception as e:
            logger.warning("Failed to log raw line: %s", e)

    async def get_server_logs(self, session_id: int) -> List[Dict[str, Any]]:
        """Retrieve all raw server log lines for a session."""
        try:
            conn = await self._get_conn()
            async with conn.execute(
                "SELECT * FROM server_logs WHERE session_id = ? ORDER BY logged_at ASC",
                (session_id,),
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.warning("Failed to get server logs: %s", e)
            return []

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
        search: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Query and return logged messages, optionally filtering by method, direction, and text search."""
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

            if search is not None:
                query += " AND (params LIKE ? OR result LIKE ? OR error LIKE ?)"
                search_pat = f"%{search}%"
                params.extend([search_pat, search_pat, search_pat])

            query += " ORDER BY timestamp ASC, id ASC"

            if limit is not None:
                query += " LIMIT ?"
                params.append(limit)
            elif offset is not None:
                # SQLite requires LIMIT to be present if OFFSET is specified
                query += " LIMIT -1"

            if offset is not None:
                query += " OFFSET ?"
                params.append(offset)

            async with conn.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.warning("Failed to get messages: %s", e)
            return []

    async def iter_messages(
        self,
        session_id: int,
        method: Optional[str] = None,
        direction: Optional[str] = None,
        chunk_size: int = 200,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Stream messages one-by-one from a DB cursor to avoid loading all into RAM.

        Usage::

            async for msg in db.iter_messages(session_id):
                process(msg)

        ``chunk_size`` controls how many rows are fetched from SQLite per round-trip.
        """
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
            query += " ORDER BY timestamp ASC, id ASC"

            async with conn.execute(query, params) as cursor:
                while True:
                    rows = await cursor.fetchmany(chunk_size)
                    if not rows:
                        break
                    for row in rows:
                        yield dict(row)
        except Exception as e:
            logger.warning("Failed to iter messages: %s", e)
            return

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

    async def get_tool_usage_count(self, session_id: int, tool_name: str) -> int:
        """Count how many times a tool was called in a session."""
        try:
            conn = await self._get_conn()
            try:
                # Try to use json_extract first.
                async with conn.execute(
                    """
                    SELECT COUNT(*) FROM messages
                    WHERE session_id = ?
                      AND method = 'tools/call'
                      AND json_extract(params, '$.name') = ?
                    """,
                    (session_id, tool_name),
                ) as cursor:
                    row = await cursor.fetchone()
                    return int(row[0]) if row else 0
            except sqlite3.OperationalError:
                # Fallback to substring matching if json_extract is not supported
                like_pattern = f'%"name":"{tool_name}"%'
                async with conn.execute(
                    """
                    SELECT COUNT(*) FROM messages
                    WHERE session_id = ?
                      AND method = 'tools/call'
                      AND params LIKE ?
                    """,
                    (session_id, like_pattern),
                ) as cursor:
                    row = await cursor.fetchone()
                    return int(row[0]) if row else 0
        except Exception as e:
            logger.warning("Failed to get tool usage count: %s", e)
            return 0

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

    async def get_replay_messages(self, session_id: int) -> List[Dict[str, Any]]:
        """Load client requests/notifications and their matched original responses for replay."""
        try:
            conn = await self._get_conn()
            query = """
                SELECT 
                    req.id AS req_id, 
                    req.message_id AS req_msg_id, 
                    req.method, 
                    req.params, 
                    req.message_type,
                    resp.id AS resp_id,
                    resp.result AS resp_result,
                    resp.error AS resp_error
                FROM messages req
                LEFT JOIN messages resp ON 
                    resp.session_id = req.session_id AND 
                    resp.message_id = req.message_id AND 
                    resp.direction = 'server_to_client' AND 
                    resp.message_type = 'response'
                WHERE req.session_id = ? AND req.direction = 'client_to_server'
                ORDER BY req.timestamp ASC
            """
            async with conn.execute(query, (session_id,)) as cursor:
                rows = await cursor.fetchall()
                results = []
                for row in rows:
                    params = None
                    if row["params"] is not None:
                        try:
                            params = json.loads(row["params"])
                        except Exception:
                            params = row["params"]

                    original_response = None
                    if row["resp_id"] is not None:
                        # Reconstruct the original response JSON-RPC message
                        msg_id = row["req_msg_id"]
                        if msg_id is not None:
                            try:
                                msg_id = int(msg_id)
                            except ValueError:
                                pass
                        original_response = {
                            "jsonrpc": "2.0",
                            "id": msg_id,
                        }
                        if row["resp_result"] is not None:
                            try:
                                original_response["result"] = json.loads(row["resp_result"])
                            except Exception:
                                original_response["result"] = row["resp_result"]
                        if row["resp_error"] is not None:
                            try:
                                original_response["error"] = json.loads(row["resp_error"])
                            except Exception:
                                original_response["error"] = row["resp_error"]

                    results.append(
                        {
                            "original_message_id": row["req_id"],
                            "message_id": row["req_msg_id"],
                            "method": row["method"],
                            "params": params,
                            "message_type": row["message_type"],
                            "original_response": original_response,
                        }
                    )
                return results
        except Exception as e:
            logger.warning("Failed to get replay messages: %s", e)
            return []

    async def save_replay(
        self,
        source_session_id: int,
        target_server_command: str,
        status: str,
        total_messages: int,
        mismatches: int,
        messages: List[Dict[str, Any]],
        started_at: str,
        ended_at: str,
    ) -> int:
        """Save a replay run and its individual replayed messages to the database."""
        try:
            conn = await self._get_conn()
            async with conn.execute(
                """
                INSERT INTO replays (
                    source_session_id, target_server_command, started_at, ended_at, status, total_messages, mismatches
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_session_id,
                    target_server_command,
                    started_at,
                    ended_at,
                    status,
                    total_messages,
                    mismatches,
                ),
            ) as cursor:
                replay_id = cursor.lastrowid

            if replay_id is not None:
                for msg in messages:
                    # original_response_json
                    orig_resp = msg.get("original_response")
                    orig_resp_str = json.dumps(orig_resp) if orig_resp is not None else None

                    # replayed_response_json
                    repl_resp = msg.get("replayed_response")
                    repl_resp_str = json.dumps(repl_resp) if repl_resp is not None else None

                    await conn.execute(
                        """
                        INSERT INTO replay_messages (
                            replay_id, original_message_id, original_response_json, replayed_response_json, matches, error, latency_ms
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            replay_id,
                            msg["original_message_id"],
                            orig_resp_str,
                            repl_resp_str,
                            msg.get("matches", False),
                            msg.get("error"),
                            msg.get("latency_ms"),
                        ),
                    )
            await conn.commit()
            return replay_id if replay_id is not None else -1
        except Exception as e:
            logger.warning("Failed to save replay: %s", e)
            return -1
