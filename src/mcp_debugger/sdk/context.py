"""Context propagation for active agent, session, and tracing backend."""

from __future__ import annotations

import contextvars
from typing import Any

_current_agent: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "mcp_debugger_current_agent", default=None
)
_current_session_id: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "mcp_debugger_current_session_id", default=None
)
_current_step_counter: contextvars.ContextVar[int] = contextvars.ContextVar(
    "mcp_debugger_step_counter", default=0
)
_tracer_backend: contextvars.ContextVar[Any] = contextvars.ContextVar(
    "mcp_debugger_tracer_backend", default=None
)


def get_current_agent() -> str | None:
    """Return the name of the currently active agent in this execution context."""
    return _current_agent.get()


def set_current_agent(name: str | None) -> contextvars.Token[str | None]:
    """Set the active agent name in the current context."""
    return _current_agent.set(name)


def reset_current_agent(token: contextvars.Token[str | None]) -> None:
    """Reset the active agent name using its restoration token."""
    _current_agent.reset(token)


def get_current_session_id() -> int | None:
    """Return the active session ID, or None if tracing is inactive."""
    return _current_session_id.get()


def get_tracer_backend() -> Any:
    """Return the active tracing backend, or None if inactive."""
    return _tracer_backend.get()


def set_active_session(session_id: int | None, backend: Any = None) -> None:
    """Activate or deactivate tracing for a specific session ID and backend."""
    _current_session_id.set(session_id)
    _tracer_backend.set(backend)
    if session_id is None:
        _current_step_counter.set(0)


def next_step_index() -> int:
    """Atomically increment and return the next step index for this context."""
    idx = _current_step_counter.get()
    _current_step_counter.set(idx + 1)
    return idx
