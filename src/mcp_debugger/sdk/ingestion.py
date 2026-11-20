"""Direct in-process trace ingestion engine for the Python SDK."""

from __future__ import annotations

import atexit
import asyncio
import os
import weakref
from pathlib import Path
from typing import Any

from mcp_debugger.sdk.context import set_active_session
from mcp_debugger.storage.database import Database

_active_sessions: weakref.WeakSet[TraceSession] = weakref.WeakSet()


def _resolve_db_path(db_path: str | None = None) -> str:
    """Resolve database path from argument, environment, or default."""
    if db_path is not None:
        return db_path
    env_path = os.environ.get("MCP_DEBUGGER_DATABASE_PATH") or os.environ.get("MCP_DEBUGGER_DB_PATH")
    if env_path is not None:
        return env_path
    home_dir = Path.home() / ".mcp-debugger"
    home_dir.mkdir(parents=True, exist_ok=True)
    return str(home_dir / "sessions.db")


class TraceSession:
    """In-process tracing session backed directly by SQLite."""

    def __init__(
        self,
        friendly_name: str | None = None,
        server_command: str = "in-process",
        db_path: str | None = None,
    ) -> None:
        self.friendly_name = friendly_name
        self.server_command = server_command
        self.db_path = _resolve_db_path(db_path)
        self.db = Database(db_path=self.db_path)
        self.session_id: int = 0
        self._closed = False
        self._pending_tasks: set[asyncio.Task[Any]] = set()

    def _init_sync(self) -> None:
        if self.session_id == 0:

            async def _run() -> None:
                await self.db.connect()
                self.session_id = await self.db.create_session(
                    server_command=self.server_command,
                    friendly_name=self.friendly_name,
                )

            asyncio.run(_run())
            set_active_session(self.session_id, self)
            _active_sessions.add(self)

    async def _init_async(self) -> None:
        if self.session_id == 0:
            await self.db.connect()
            self.session_id = await self.db.create_session(
                server_command=self.server_command,
                friendly_name=self.friendly_name,
            )
            set_active_session(self.session_id, self)
            _active_sessions.add(self)

    def record_step(
        self,
        session_id: int,
        step_index: int,
        step_type: str,
        agent_name: str | None,
        input_data: str | None,
        output_data: str | None,
        latency_ms: float | None,
        tokens_input: int | None = None,
        tokens_output: int | None = None,
    ) -> Any:
        """Record step into SQLite database."""
        if self._closed:
            return None

        async def _log() -> int:
            return await self.db.log_step(
                session_id=session_id,
                step_index=step_index,
                step_type=step_type,
                agent_name=agent_name,
                input_data=input_data,
                output_data=output_data,
                tokens_input=tokens_input,
                tokens_output=tokens_output,
                latency_ms=latency_ms,
            )

        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(_log())
            self._pending_tasks.add(task)
            task.add_done_callback(self._pending_tasks.discard)
            return task
        except RuntimeError:
            return asyncio.run(_log())

    def close(self, status: str = "completed") -> None:
        """Close session synchronously."""
        if self._closed:
            return
        self._closed = True

        async def _close() -> None:
            if self._pending_tasks:
                await asyncio.gather(*self._pending_tasks, return_exceptions=True)
            await self.db.close_session(self.session_id, status=status)
            await self.db.close()

        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(_close())
            self._pending_tasks.add(task)
        except RuntimeError:
            asyncio.run(_close())

        set_active_session(None, None)

    async def aclose(self, status: str = "completed") -> None:
        """Close session asynchronously."""
        if self._closed:
            return
        self._closed = True
        if self._pending_tasks:
            await asyncio.gather(*self._pending_tasks, return_exceptions=True)
        await self.db.close_session(self.session_id, status=status)
        await self.db.close()
        set_active_session(None, None)

    def __enter__(self) -> TraceSession:
        self._init_sync()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        status = "errored" if exc_type is not None else "completed"
        self.close(status=status)

    async def __aenter__(self) -> TraceSession:
        await self._init_async()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        status = "errored" if exc_type is not None else "completed"
        await self.aclose(status=status)


def start_trace(
    friendly_name: str | None = None,
    server_command: str = "in-process",
    db_path: str | None = None,
) -> TraceSession:
    """Start an in-process tracing session and configure SDK context."""
    session = TraceSession(
        friendly_name=friendly_name,
        server_command=server_command,
        db_path=db_path,
    )
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        session._init_sync()
    return session


@atexit.register
def _atexit_flush() -> None:
    """Flush and close any remaining active trace sessions on process exit."""
    for session in list(_active_sessions):
        try:
            session.close()
        except Exception:
            pass
