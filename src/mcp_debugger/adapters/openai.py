"""OpenAI Agents SDK adapter for MCP Debugger."""

from __future__ import annotations

import functools
import json
import time
from typing import Any

from mcp_debugger.sdk.context import (
    get_current_session_id,
    get_tracer_backend,
    next_step_index,
)

try:
    import openai  # noqa: F401

    _OPENAI_AVAILABLE = True
except ImportError:
    _OPENAI_AVAILABLE = False


def _safe_json(val: Any) -> str:
    """Format value safely into JSON or string."""
    try:
        if isinstance(val, str):
            return val
        if isinstance(val, (dict, list)):
            return json.dumps(val, default=str)
        return str(val)
    except Exception:
        return repr(val)


class OpenAIAgentTracker:
    """Tracks OpenAI agent events and records trajectory steps into the active session."""

    def __init__(self, agent_name: str = "openai_agent") -> None:
        self.agent_name = agent_name
        self._llm_start_time: float | None = None
        self._llm_prompt: str | None = None
        self._llm_model: str | None = None

        self._tool_start_time: float | None = None
        self._tool_args: dict[str, Any] = {}

    def on_llm_start(self, model: str, prompt: Any) -> None:
        """Invoked when model request begins."""
        self._llm_start_time = time.perf_counter()
        self._llm_model = model
        self._llm_prompt = _safe_json(prompt)

    def on_llm_end(self, response: Any, usage: dict[str, Any] | None = None) -> None:
        """Invoked when model response is received."""
        session_id = get_current_session_id()
        backend = get_tracer_backend()
        if session_id is None or backend is None:
            return

        latency = (
            (time.perf_counter() - self._llm_start_time) * 1000.0
            if self._llm_start_time is not None
            else None
        )
        tokens_in = None
        tokens_out = None
        if isinstance(usage, dict):
            tokens_in = usage.get("prompt_tokens") or usage.get("input_tokens")
            tokens_out = usage.get("completion_tokens") or usage.get("output_tokens")

        step_idx = next_step_index()
        input_payload = {
            "model": self._llm_model,
            "prompt": self._llm_prompt,
        }
        backend.record_step(
            session_id=session_id,
            step_index=step_idx,
            step_type="llm_call",
            agent_name=self.agent_name,
            input_data=_safe_json(input_payload),
            output_data=_safe_json(response),
            latency_ms=round(latency, 2) if latency is not None else None,
            tokens_input=int(tokens_in) if tokens_in is not None else None,
            tokens_output=int(tokens_out) if tokens_out is not None else None,
        )

    def on_tool_start(self, tool_name: str, arguments: Any) -> None:
        """Invoked when a tool call begins."""
        self._tool_start_time = time.perf_counter()
        self._tool_args = arguments

    def on_tool_end(self, tool_name: str, result: Any) -> None:
        """Invoked when a tool execution completes."""
        session_id = get_current_session_id()
        backend = get_tracer_backend()
        if session_id is None or backend is None:
            return

        latency = (
            (time.perf_counter() - self._tool_start_time) * 1000.0
            if self._tool_start_time is not None
            else None
        )
        step_idx = next_step_index()
        input_payload = {
            "tool": tool_name,
            "arguments": self._tool_args,
        }
        backend.record_step(
            session_id=session_id,
            step_index=step_idx,
            step_type="tool_call",
            agent_name=self.agent_name,
            input_data=_safe_json(input_payload),
            output_data=_safe_json(result),
            latency_ms=round(latency, 2) if latency is not None else None,
        )

    def on_handoff(self, target_agent: str, context: Any = None) -> None:
        """Invoked when control is handed off from one agent to another."""
        session_id = get_current_session_id()
        backend = get_tracer_backend()
        if session_id is None or backend is None:
            return

        step_idx = next_step_index()
        input_payload = {
            "from_agent": self.agent_name,
            "to_agent": target_agent,
            "context": context,
        }
        backend.record_step(
            session_id=session_id,
            step_index=step_idx,
            step_type="handoff",
            agent_name=self.agent_name,
            input_data=_safe_json(input_payload),
            output_data=f"Handoff to {target_agent}",
            latency_ms=0.0,
        )


def trace_openai_agent(agent_or_runner: Any) -> Any:
    """Wrap an OpenAI Agent or Runner object to intercept executions into trajectory steps."""
    agent_name = getattr(agent_or_runner, "name", None) or "openai_agent"

    if hasattr(agent_or_runner, "run"):
        orig_run = agent_or_runner.run

        @functools.wraps(orig_run)
        def wrapped_run(*args: Any, **kwargs: Any) -> Any:
            session_id = get_current_session_id()
            backend = get_tracer_backend()
            start_time = time.perf_counter()
            try:
                res = orig_run(*args, **kwargs)
                if session_id is not None and backend is not None:
                    latency = (time.perf_counter() - start_time) * 1000.0
                    step_idx = next_step_index()
                    input_str = _safe_json(args[0] if len(args) == 1 else {"args": args, "kwargs": kwargs})
                    backend.record_step(
                        session_id=session_id,
                        step_index=step_idx,
                        step_type="thought",
                        agent_name=agent_name,
                        input_data=input_str,
                        output_data=_safe_json(res),
                        latency_ms=round(latency, 2),
                    )
                return res
            except Exception as exc:
                if session_id is not None and backend is not None:
                    latency = (time.perf_counter() - start_time) * 1000.0
                    step_idx = next_step_index()
                    input_str = _safe_json(args[0] if len(args) == 1 else {"args": args, "kwargs": kwargs})
                    backend.record_step(
                        session_id=session_id,
                        step_index=step_idx,
                        step_type="thought",
                        agent_name=agent_name,
                        input_data=input_str,
                        output_data=f"Error: {type(exc).__name__}: {exc}",
                        latency_ms=round(latency, 2),
                    )
                raise

        agent_or_runner.run = wrapped_run
        return agent_or_runner

    return agent_or_runner
