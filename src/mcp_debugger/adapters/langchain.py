"""LangChain v0.2+ callback handler adapter for MCP Debugger."""

from __future__ import annotations

import json
import time
from typing import Any

from mcp_debugger.sdk.context import (
    get_current_session_id,
    get_tracer_backend,
    next_step_index,
)

try:
    from langchain_core.callbacks.base import BaseCallbackHandler

    _LANGCHAIN_AVAILABLE = True
except ImportError:
    _LANGCHAIN_AVAILABLE = False

    class BaseCallbackHandler:  # type: ignore[no-redef]
        """Fallback stub when langchain_core is absent."""

        pass


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


class MCPDebuggerCallbackHandler(BaseCallbackHandler):
    """LangChain callback handler recording chain, tool, and LLM events into trajectory steps."""

    def __init__(self, agent_name: str = "langchain_agent") -> None:
        super().__init__()
        self.agent_name = agent_name
        self._runs: dict[Any, dict[str, Any]] = {}

    # --- Chains (step_type='thought') ---

    def on_chain_start(
        self,
        serialized: dict[str, Any] | None,
        inputs: dict[str, Any],
        *,
        run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        """Record chain execution start."""
        chain_name = serialized.get("name") if isinstance(serialized, dict) else None
        input_payload = {"chain": chain_name, "inputs": inputs} if chain_name else inputs
        self._runs[run_id] = {
            "start_time": time.perf_counter(),
            "step_type": "thought",
            "agent_name": self.agent_name,
            "input": _safe_json(input_payload),
        }

    def on_chain_end(
        self,
        outputs: dict[str, Any],
        *,
        run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        """Record chain execution end."""
        self._finish_run(run_id=run_id, output=_safe_json(outputs))

    def on_chain_error(
        self,
        error: BaseException,
        *,
        run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        """Record chain execution failure."""
        self._finish_run(run_id=run_id, output=f"Error: {type(error).__name__}: {error}")

    # --- Tools (step_type='tool_call') ---

    def on_tool_start(
        self,
        serialized: dict[str, Any] | None,
        input_str: str,
        *,
        run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        """Record tool execution start."""
        tool_name = serialized.get("name") if isinstance(serialized, dict) else "unknown_tool"
        input_payload = {"tool": tool_name, "input": input_str}
        self._runs[run_id] = {
            "start_time": time.perf_counter(),
            "step_type": "tool_call",
            "agent_name": self.agent_name,
            "input": _safe_json(input_payload),
        }

    def on_tool_end(
        self,
        output: Any,
        *,
        run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        """Record tool execution end."""
        self._finish_run(run_id=run_id, output=_safe_json(output))

    def on_tool_error(
        self,
        error: BaseException,
        *,
        run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        """Record tool execution failure."""
        self._finish_run(run_id=run_id, output=f"Error: {type(error).__name__}: {error}")

    # --- LLM Calls (step_type='llm_call') ---

    def on_llm_start(
        self,
        serialized: dict[str, Any] | None,
        prompts: list[str],
        *,
        run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        """Record LLM call start."""
        model_name = None
        if isinstance(serialized, dict):
            kwargs_dict = serialized.get("kwargs", {})
            model_name = kwargs_dict.get("model_name") or kwargs_dict.get("model")
        input_payload = {"model": model_name, "prompts": prompts}
        self._runs[run_id] = {
            "start_time": time.perf_counter(),
            "step_type": "llm_call",
            "agent_name": self.agent_name,
            "input": _safe_json(input_payload),
        }

    def on_llm_end(
        self,
        response: Any,
        *,
        run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        """Record LLM call end, extracting token metrics."""
        tokens_in = None
        tokens_out = None
        output_text = ""

        llm_output = getattr(response, "llm_output", None)
        if isinstance(llm_output, dict):
            usage = llm_output.get("token_usage", {})
            if isinstance(usage, dict):
                tokens_in = usage.get("prompt_tokens") or usage.get("input_tokens")
                tokens_out = usage.get("completion_tokens") or usage.get("output_tokens")

        generations = getattr(response, "generations", None)
        if generations and isinstance(generations, list) and len(generations) > 0:
            first_gen = generations[0]
            if isinstance(first_gen, list) and len(first_gen) > 0:
                output_text = getattr(first_gen[0], "text", str(first_gen[0]))
            else:
                output_text = getattr(first_gen, "text", str(first_gen))

        self._finish_run(
            run_id=run_id,
            output=output_text or _safe_json(response),
            tokens_input=int(tokens_in) if tokens_in is not None else None,
            tokens_output=int(tokens_out) if tokens_out is not None else None,
        )

    def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        """Record LLM call failure."""
        self._finish_run(run_id=run_id, output=f"Error: {type(error).__name__}: {error}")

    def _finish_run(
        self,
        run_id: Any,
        output: str,
        tokens_input: int | None = None,
        tokens_output: int | None = None,
    ) -> None:
        """Complete a run and record step with backend."""
        run_info = self._runs.pop(run_id, None)
        if run_info is None:
            return

        session_id = get_current_session_id()
        backend = get_tracer_backend()
        if session_id is None or backend is None:
            return

        latency = (time.perf_counter() - run_info["start_time"]) * 1000.0
        step_idx = next_step_index()

        backend.record_step(
            session_id=session_id,
            step_index=step_idx,
            step_type=run_info["step_type"],
            agent_name=run_info["agent_name"],
            input_data=run_info["input"],
            output_data=output,
            latency_ms=round(latency, 2),
            tokens_input=tokens_input,
            tokens_output=tokens_output,
        )
