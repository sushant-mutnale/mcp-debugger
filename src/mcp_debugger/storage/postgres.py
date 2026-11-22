"""PostgreSQL team storage backend using asyncpg."""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

logger = logging.getLogger("mcp_debugger.storage.postgres")


def normalize_postgres_url(url: str) -> str:
    """Normalize postgres URLs to standard postgresql:// format."""
    normalized = url.strip()
    if normalized.startswith("postgresql+asyncpg://"):
        normalized = "postgresql://" + normalized[len("postgresql+asyncpg://") :]
    elif normalized.startswith("postgres://"):
        normalized = "postgresql://" + normalized[len("postgres://") :]
    return normalized


class PostgresDatabase:
    """Handles PostgreSQL database interactions using asyncpg for centralized team storage."""

    def __init__(self, database_url: str) -> None:
        self.database_url = normalize_postgres_url(database_url)
        self._pool: Any = None

    async def connect(self) -> None:
        """Establish PostgreSQL connection pool and initialize relational schemas."""
        try:
            import asyncpg
        except ImportError as e:
            raise ImportError(
                "PostgreSQL support requires 'asyncpg'. "
                "Install with: pip install 'mcp-debugger[postgres]'"
            ) from e

        self._pool = await asyncpg.create_pool(
            self.database_url,
            min_size=1,
            max_size=10,
        )
        await self._create_tables()

    async def close(self) -> None:
        """Close PostgreSQL connection pool."""
        if self._pool is not None:
            import inspect

            if hasattr(self._pool, "close"):
                res = self._pool.close()
                if inspect.isawaitable(res):
                    await res
            self._pool = None

    async def _create_tables(self) -> None:
        """Create PostgreSQL tables and indexes if they do not exist."""
        async with self._pool.acquire() as conn:
            # 1. sessions
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id SERIAL PRIMARY KEY,
                    session_uuid TEXT UNIQUE NOT NULL,
                    friendly_name TEXT,
                    server_command TEXT NOT NULL,
                    server_name TEXT,
                    started_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    ended_at TIMESTAMP WITH TIME ZONE,
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

            # 2. messages
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id SERIAL PRIMARY KEY,
                    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    message_id TEXT,
                    direction TEXT CHECK(direction IN ('client_to_server', 'server_to_client')),
                    method TEXT,
                    params TEXT,
                    result TEXT,
                    error TEXT,
                    timestamp REAL,
                    latency_ms REAL,
                    message_type TEXT CHECK(message_type IN ('request', 'response', 'notification'))
                );
                """
            )

            # 3. agents
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS agents (
                    id SERIAL PRIMARY KEY,
                    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    parent_agent_id INTEGER REFERENCES agents(id) ON DELETE SET NULL,
                    name TEXT NOT NULL,
                    role TEXT,
                    framework TEXT,
                    metadata TEXT,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

            # 4. steps
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS steps (
                    id SERIAL PRIMARY KEY,
                    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    step_index INTEGER NOT NULL,
                    step_type TEXT CHECK(step_type IN ('llm_call', 'tool_call', 'thought', 'handoff')),
                    agent_name TEXT,
                    agent_id INTEGER REFERENCES agents(id) ON DELETE SET NULL,
                    input TEXT,
                    output TEXT,
                    content_hash TEXT,
                    tokens_input INTEGER,
                    tokens_output INTEGER,
                    latency_ms REAL,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

            # 5. attributions
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS attributions (
                    id SERIAL PRIMARY KEY,
                    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    poc_step_index INTEGER,
                    failure_category TEXT CHECK(failure_category IN ('agent', 'tool', 'protocol', 'none')),
                    root_cause_explanation TEXT,
                    mode TEXT,
                    details TEXT,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

            # 6. tools
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tools (
                    id SERIAL PRIMARY KEY,
                    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    description TEXT,
                    input_schema TEXT,
                    first_seen_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

            # 7. errors
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS errors (
                    id SERIAL PRIMARY KEY,
                    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    message_id INTEGER REFERENCES messages(id) ON DELETE SET NULL,
                    code INTEGER,
                    message TEXT NOT NULL,
                    data TEXT,
                    category TEXT,
                    timestamp REAL
                );
                """
            )

            # 8. replays
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS replays (
                    id SERIAL PRIMARY KEY,
                    source_session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    target_server_command TEXT NOT NULL,
                    started_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    ended_at TIMESTAMP WITH TIME ZONE,
                    status TEXT,
                    total_messages INTEGER,
                    mismatches INTEGER
                );
                """
            )

            # 9. replay_messages
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS replay_messages (
                    id SERIAL PRIMARY KEY,
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

    # ------------------------------------------------------------------
    # CRUD Operations
    # ------------------------------------------------------------------

    async def create_session(
        self,
        server_command: str,
        friendly_name: str | None = None,
        client_info: str | None = None,
        server_info: str | None = None,
        protocol_version: str | None = None,
    ) -> int:
        session_uuid = str(uuid.uuid4())
        async with self._pool.acquire() as conn:
            sid = await conn.fetchval(
                """
                INSERT INTO sessions (
                    session_uuid, friendly_name, server_command, client_info, server_info, protocol_version
                ) VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id;
                """,
                session_uuid,
                friendly_name,
                server_command,
                client_info,
                server_info,
                protocol_version,
            )
            return int(sid)

    async def get_session(self, session_id: int) -> dict[str, Any] | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM sessions WHERE id = $1", session_id)
            return dict(row) if row else None

    async def get_sessions(
        self,
        limit: int | None = None,
        offset: int | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM sessions"
        params: list[Any] = []
        if status:
            params.append(status)
            query += f" WHERE status = ${len(params)}"
        query += " ORDER BY id DESC"
        if limit is not None:
            params.append(limit)
            query += f" LIMIT ${len(params)}"
        if offset is not None:
            params.append(offset)
            query += f" OFFSET ${len(params)}"

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            return [dict(r) for r in rows]

    async def list_sessions(
        self,
        limit: int | None = None,
        offset: int | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        return await self.get_sessions(limit=limit, offset=offset, status=status)

    async def log_message(
        self,
        session_id: int,
        direction: str,
        message: dict[str, Any] | Any,
    ) -> int:
        msg_dict = message if isinstance(message, dict) else dict(message)
        msg_id = msg_dict.get("id")
        msg_id_str = str(msg_id) if msg_id is not None else None
        method = msg_dict.get("method")
        params = json.dumps(msg_dict["params"]) if msg_dict.get("params") is not None else None
        result = json.dumps(msg_dict["result"]) if msg_dict.get("result") is not None else None
        error = json.dumps(msg_dict["error"]) if msg_dict.get("error") is not None else None

        if msg_id_str is not None:
            message_type = "request" if method is not None else "response"
        else:
            message_type = "notification"

        ts = time.time() * 1000.0
        latency_ms: float | None = None

        async with self._pool.acquire() as conn:
            if message_type == "response" and msg_id_str is not None:
                row = await conn.fetchrow(
                    """
                    SELECT timestamp, method FROM messages
                    WHERE session_id = $1 AND message_id = $2 AND message_type = 'request'
                    ORDER BY timestamp DESC LIMIT 1
                    """,
                    session_id,
                    msg_id_str,
                )
                if row:
                    latency_ms = ts - row["timestamp"]
                    method = row["method"]

            mid = await conn.fetchval(
                """
                INSERT INTO messages (
                    session_id, message_id, direction, method, params, result, error, timestamp, latency_ms, message_type
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                RETURNING id;
                """,
                session_id,
                msg_id_str,
                direction,
                method,
                params,
                result,
                error,
                ts,
                latency_ms,
                message_type,
            )
            await conn.execute(
                "UPDATE sessions SET total_messages = total_messages + 1 WHERE id = $1",
                session_id,
            )
            return int(mid)

    async def get_messages(
        self,
        session_id: int,
        limit: int | None = None,
        offset: int | None = None,
        method: str | None = None,
        direction: str | None = None,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM messages WHERE session_id = $1"
        params: list[Any] = [session_id]

        if method:
            params.append(method)
            query += f" AND method = ${len(params)}"
        if direction:
            params.append(direction)
            query += f" AND direction = ${len(params)}"

        query += " ORDER BY timestamp ASC, id ASC"
        if limit is not None:
            params.append(limit)
            query += f" LIMIT ${len(params)}"
        if offset is not None:
            params.append(offset)
            query += f" OFFSET ${len(params)}"

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            return [dict(r) for r in rows]

    async def log_step(
        self,
        session_id: int,
        step_index: int,
        step_type: str,
        agent_name: str | None = None,
        agent_id: int | None = None,
        input_data: str | None = None,
        output_data: str | None = None,
        content_hash: str | None = None,
        tokens_input: int | None = None,
        tokens_output: int | None = None,
        latency_ms: float | None = None,
    ) -> int:
        async with self._pool.acquire() as conn:
            step_id = await conn.fetchval(
                """
                INSERT INTO steps (
                    session_id, step_index, step_type, agent_name, agent_id,
                    input, output, content_hash, tokens_input, tokens_output, latency_ms
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                RETURNING id;
                """,
                session_id,
                step_index,
                step_type,
                agent_name,
                agent_id,
                input_data,
                output_data,
                content_hash,
                tokens_input,
                tokens_output,
                latency_ms,
            )
            return int(step_id)

    async def get_steps(
        self,
        session_id: int,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM steps WHERE session_id = $1 ORDER BY step_index ASC, id ASC"
        params: list[Any] = [session_id]
        if limit is not None:
            params.append(limit)
            query += f" LIMIT ${len(params)}"
        if offset is not None:
            params.append(offset)
            query += f" OFFSET ${len(params)}"

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            return [dict(r) for r in rows]

    async def create_agent(
        self,
        session_id: int,
        name: str,
        role: str | None = None,
        framework: str | None = None,
        parent_agent_id: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        meta_json = json.dumps(metadata) if metadata else None
        async with self._pool.acquire() as conn:
            aid = await conn.fetchval(
                """
                INSERT INTO agents (
                    session_id, parent_agent_id, name, role, framework, metadata
                ) VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id;
                """,
                session_id,
                parent_agent_id,
                name,
                role,
                framework,
                meta_json,
            )
            return int(aid)

    async def get_agent(self, agent_id: int) -> dict[str, Any] | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM agents WHERE id = $1", agent_id)
            return dict(row) if row else None

    async def get_agents(self, session_id: int) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM agents WHERE session_id = $1 ORDER BY id ASC",
                session_id,
            )
            return [dict(r) for r in rows]

    async def get_agent_hierarchy(self, session_id: int) -> list[dict[str, Any]]:
        agents = await self.get_agents(session_id)
        if not agents:
            return []

        children_map: dict[int, list[dict[str, Any]]] = {}
        roots: list[dict[str, Any]] = []

        for a in agents:
            a["children"] = []
            pid = a.get("parent_agent_id")
            if pid is not None:
                children_map.setdefault(pid, []).append(a)
            else:
                roots.append(a)

        def _attach(agent_node: dict[str, Any]) -> None:
            aid = agent_node.get("id")
            if aid is not None and aid in children_map:
                agent_node["children"] = children_map[aid]
                for child in agent_node["children"]:
                    _attach(child)

        for root in roots:
            _attach(root)

        return roots

    async def log_attribution(
        self,
        session_id: int,
        poc_step_index: int | None,
        failure_category: str,
        root_cause_explanation: str,
        mode: str = "vcr",
        details: dict[str, Any] | None = None,
    ) -> int:
        details_json = json.dumps(details) if details else None
        async with self._pool.acquire() as conn:
            att_id = await conn.fetchval(
                """
                INSERT INTO attributions (
                    session_id, poc_step_index, failure_category, root_cause_explanation, mode, details
                ) VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id;
                """,
                session_id,
                poc_step_index,
                failure_category,
                root_cause_explanation,
                mode,
                details_json,
            )
            return int(att_id)

    async def get_attribution(self, session_id: int) -> dict[str, Any] | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM attributions WHERE session_id = $1 ORDER BY id DESC LIMIT 1",
                session_id,
            )
            return dict(row) if row else None

    async def get_tools(self, session_id: int) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM tools WHERE session_id = $1", session_id)
            return [dict(r) for r in rows]

    async def get_errors(self, session_id: int) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM errors WHERE session_id = $1 ORDER BY timestamp ASC",
                session_id,
            )
            return [dict(r) for r in rows]

    async def get_replays(self, session_id: int) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM replays WHERE source_session_id = $1 ORDER BY id ASC",
                session_id,
            )
            return [dict(r) for r in rows]
