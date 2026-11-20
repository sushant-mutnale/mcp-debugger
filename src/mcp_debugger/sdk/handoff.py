"""Inter-agent handoff tracking and context state diff capture."""

from __future__ import annotations

import functools
import inspect
import json
import time
from typing import Any, Callable

from mcp_debugger.sdk.context import (
    get_current_session_id,
    next_step_index,
    reset_current_agent,
    set_current_agent,
)
from mcp_debugger.sdk.decorators import _dispatch_record_step, _dispatch_record_step_async


def calculate_context_diff(initial: Any, updated: Any) -> dict[str, Any]:
    """Calculate the delta/diff between upstream context and downstream context."""
    if isinstance(initial, dict) and isinstance(updated, dict):
        added = {k: updated[k] for k in updated if k not in initial}
        removed = [k for k in initial if k not in updated]
        modified = {
            k: {"old": initial[k], "new": updated[k]}
            for k in initial
            if k in updated and initial[k] != updated[k]
        }
        return {"added": added, "removed": removed, "modified": modified}

    return {
        "changed": initial != updated,
        "old": initial,
        "new": updated,
    }


class HandoffContext:
    """Context manager for tracing inter-agent handoffs with context diffs."""

    def __init__(
        self,
        from_agent: str,
        to_agent: str,
        task: str | None = None,
        initial_context: Any = None,
    ) -> None:
        self.from_agent = from_agent
        self.to_agent = to_agent
        self.task = task
        self.initial_context = initial_context or {}
        self.output_context: Any = None
        self._start_time: float = 0.0
        self._session_id: int = 0
        self._step_index: int = 0
        self._token: Any = None

    def set_output_context(self, context: Any) -> None:
        """Update the handoff result context."""
        self.output_context = context

    def _prepare_entry(self) -> None:
        self._session_id = get_current_session_id()
        self._step_index = next_step_index()
        self._start_time = time.perf_counter()
        self._token = set_current_agent(self.to_agent)

    def _prepare_exit(self) -> None:
        latency_ms = (time.perf_counter() - self._start_time) * 1000.0
        if self._token is not None:
            reset_current_agent(self._token)

        if self._session_id == 0:
            return

        diff = calculate_context_diff(
            self.initial_context,
            self.output_context if self.output_context is not None else self.initial_context,
        )

        input_payload = {
            "from_agent": self.from_agent,
            "to_agent": self.to_agent,
            "task": self.task,
            "transferred_context": self.initial_context,
        }
        output_payload = {
            "to_agent": self.to_agent,
            "output_context": self.output_context,
            "context_diff": diff,
        }

        _dispatch_record_step(
            session_id=self._session_id,
            step_index=self._step_index,
            step_type="handoff",
            agent_name=self.from_agent,
            input_data=json.dumps(input_payload, default=str),
            output_data=json.dumps(output_payload, default=str),
            latency_ms=latency_ms,
        )

    def __enter__(self) -> HandoffContext:
        self._prepare_entry()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if exc_val is not None and self.output_context is None:
            self.output_context = {"error": str(exc_val)}
        self._prepare_exit()

    async def __aenter__(self) -> HandoffContext:
        self._prepare_entry()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if exc_val is not None and self.output_context is None:
            self.output_context = {"error": str(exc_val)}
        latency_ms = (time.perf_counter() - self._start_time) * 1000.0
        if self._token is not None:
            reset_current_agent(self._token)

        if self._session_id == 0:
            return

        diff = calculate_context_diff(
            self.initial_context,
            self.output_context if self.output_context is not None else self.initial_context,
        )

        input_payload = {
            "from_agent": self.from_agent,
            "to_agent": self.to_agent,
            "task": self.task,
            "transferred_context": self.initial_context,
        }
        output_payload = {
            "to_agent": self.to_agent,
            "output_context": self.output_context,
            "context_diff": diff,
        }

        await _dispatch_record_step_async(
            session_id=self._session_id,
            step_index=self._step_index,
            step_type="handoff",
            agent_name=self.from_agent,
            input_data=json.dumps(input_payload, default=str),
            output_data=json.dumps(output_payload, default=str),
            latency_ms=latency_ms,
        )


def trace_handoff_context(
    from_agent: str,
    to_agent: str,
    task: str | None = None,
    initial_context: Any = None,
) -> HandoffContext:
    """Context manager for tracing inter-agent handoff delegations."""
    return HandoffContext(
        from_agent=from_agent,
        to_agent=to_agent,
        task=task,
        initial_context=initial_context,
    )


def trace_handoff(
    from_agent: str,
    to_agent: str,
    task: str | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator to trace inter-agent handoff delegation functions."""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                session_id = get_current_session_id()
                step_idx = next_step_index()
                start_time = time.perf_counter()

                initial_ctx = args[0] if args and isinstance(args[0], dict) else kwargs

                # Switch active agent context to downstream receiver
                token = set_current_agent(to_agent)
                try:
                    result = await func(*args, **kwargs)
                finally:
                    reset_current_agent(token)

                latency_ms = (time.perf_counter() - start_time) * 1000.0

                diff = calculate_context_diff(initial_ctx, result)

                input_payload = {
                    "from_agent": from_agent,
                    "to_agent": to_agent,
                    "task": task or func.__name__,
                    "transferred_context": initial_ctx,
                }
                output_payload = {
                    "to_agent": to_agent,
                    "output_context": result,
                    "context_diff": diff,
                }

                await _dispatch_record_step_async(
                    session_id=session_id,
                    step_index=step_idx,
                    step_type="handoff",
                    agent_name=from_agent,
                    input_data=json.dumps(input_payload, default=str),
                    output_data=json.dumps(output_payload, default=str),
                    latency_ms=latency_ms,
                )
                return result

            return async_wrapper

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            session_id = get_current_session_id()
            step_idx = next_step_index()
            start_time = time.perf_counter()

            initial_ctx = args[0] if args and isinstance(args[0], dict) else kwargs

            # Switch active agent context to downstream receiver
            token = set_current_agent(to_agent)
            try:
                result = func(*args, **kwargs)
            finally:
                reset_current_agent(token)

            latency_ms = (time.perf_counter() - start_time) * 1000.0

            diff = calculate_context_diff(initial_ctx, result)

            input_payload = {
                "from_agent": from_agent,
                "to_agent": to_agent,
                "task": task or func.__name__,
                "transferred_context": initial_ctx,
            }
            output_payload = {
                "to_agent": to_agent,
                "output_context": result,
                "context_diff": diff,
            }

            _dispatch_record_step(
                session_id=session_id,
                step_index=step_idx,
                step_type="handoff",
                agent_name=from_agent,
                input_data=json.dumps(input_payload, default=str),
                output_data=json.dumps(output_payload, default=str),
                latency_ms=latency_ms,
            )
            return result

        return sync_wrapper

    return decorator
