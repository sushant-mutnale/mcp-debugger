"""SDK decorators for tracing agents and MCP tools."""

from __future__ import annotations

import asyncio
import functools
import inspect
import json
import time
from typing import Any, Callable

from mcp_debugger.sdk.context import (
    get_current_agent,
    get_current_session_id,
    get_tracer_backend,
    next_step_index,
    reset_current_agent,
    set_current_agent,
)


def _format_input(name: str, args: tuple[Any, ...], kwargs: dict[str, Any], kind: str = "agent") -> str:
    """Format function arguments into a readable JSON string or repr."""
    try:
        payload: dict[str, Any] = {"name": name, "args": list(args), "kwargs": kwargs}
        if kind == "tool":
            payload["tool"] = name
        else:
            payload["agent"] = name
        return json.dumps(payload, default=str)
    except Exception:
        return f"{name}(args={args!r}, kwargs={kwargs!r})"


def _format_output(output: Any) -> str:
    """Format return value into a readable string or JSON representation."""
    try:
        if isinstance(output, str):
            return output
        if isinstance(output, (dict, list)):
            return json.dumps(output, default=str)
        return str(output)
    except Exception:
        return repr(output)


async def _dispatch_record_step_async(
    session_id: int,
    step_index: int,
    step_type: str,
    agent_name: str | None,
    input_data: str | None,
    output_data: str | None,
    latency_ms: float | None,
    tokens_input: int | None = None,
    tokens_output: int | None = None,
) -> None:
    """Send recorded step to backend from an async context."""
    backend = get_tracer_backend()
    if backend is None:
        return
    try:
        if hasattr(backend, "record_step"):
            res = backend.record_step(
                session_id=session_id,
                step_index=step_index,
                step_type=step_type,
                agent_name=agent_name,
                input_data=input_data,
                output_data=output_data,
                latency_ms=latency_ms,
                tokens_input=tokens_input,
                tokens_output=tokens_output,
            )
            if inspect.iscoroutine(res):
                await res
        elif hasattr(backend, "log_step"):
            res = backend.log_step(
                session_id=session_id,
                step_index=step_index,
                step_type=step_type,
                agent_name=agent_name,
                input_data=input_data,
                output_data=output_data,
                latency_ms=latency_ms,
                tokens_input=tokens_input,
                tokens_output=tokens_output,
            )
            if inspect.iscoroutine(res):
                await res
    except Exception:
        pass


def _dispatch_record_step(
    session_id: int,
    step_index: int,
    step_type: str,
    agent_name: str | None,
    input_data: str | None,
    output_data: str | None,
    latency_ms: float | None,
    tokens_input: int | None = None,
    tokens_output: int | None = None,
) -> None:
    """Send recorded step to the active backend from a sync context."""
    backend = get_tracer_backend()
    if backend is None:
        return
    try:
        if hasattr(backend, "record_step"):
            res = backend.record_step(
                session_id=session_id,
                step_index=step_index,
                step_type=step_type,
                agent_name=agent_name,
                input_data=input_data,
                output_data=output_data,
                latency_ms=latency_ms,
                tokens_input=tokens_input,
                tokens_output=tokens_output,
            )
            if inspect.iscoroutine(res):
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(res)
                except RuntimeError:
                    asyncio.run(res)
        elif hasattr(backend, "log_step"):
            res = backend.log_step(
                session_id=session_id,
                step_index=step_index,
                step_type=step_type,
                agent_name=agent_name,
                input_data=input_data,
                output_data=output_data,
                latency_ms=latency_ms,
                tokens_input=tokens_input,
                tokens_output=tokens_output,
            )
            if inspect.iscoroutine(res):
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(res)
                except RuntimeError:
                    asyncio.run(res)
    except Exception:
        pass


def trace_agent(name_or_func: Any = None, *, name: str | None = None) -> Any:
    """Decorator to trace an agent function or method execution."""

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        agent_name = name or (name_or_func if isinstance(name_or_func, str) else None) or fn.__name__

        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                session_id = get_current_session_id()
                if session_id is None:
                    return await fn(*args, **kwargs)

                token = set_current_agent(agent_name)
                start_time = time.perf_counter()
                input_str = _format_input(agent_name, args, kwargs)
                step_idx = next_step_index()
                try:
                    result = await fn(*args, **kwargs)
                    latency = (time.perf_counter() - start_time) * 1000.0
                    await _dispatch_record_step_async(
                        session_id=session_id,
                        step_index=step_idx,
                        step_type="thought",
                        agent_name=agent_name,
                        input_data=input_str,
                        output_data=_format_output(result),
                        latency_ms=round(latency, 2),
                    )
                    return result
                except Exception as exc:
                    latency = (time.perf_counter() - start_time) * 1000.0
                    await _dispatch_record_step_async(
                        session_id=session_id,
                        step_index=step_idx,
                        step_type="thought",
                        agent_name=agent_name,
                        input_data=input_str,
                        output_data=f"Error: {type(exc).__name__}: {exc}",
                        latency_ms=round(latency, 2),
                    )
                    raise
                finally:
                    reset_current_agent(token)

            return async_wrapper
        else:

            @functools.wraps(fn)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                session_id = get_current_session_id()
                if session_id is None:
                    return fn(*args, **kwargs)

                token = set_current_agent(agent_name)
                start_time = time.perf_counter()
                input_str = _format_input(agent_name, args, kwargs)
                step_idx = next_step_index()
                try:
                    result = fn(*args, **kwargs)
                    latency = (time.perf_counter() - start_time) * 1000.0
                    _dispatch_record_step(
                        session_id=session_id,
                        step_index=step_idx,
                        step_type="thought",
                        agent_name=agent_name,
                        input_data=input_str,
                        output_data=_format_output(result),
                        latency_ms=round(latency, 2),
                    )
                    return result
                except Exception as exc:
                    latency = (time.perf_counter() - start_time) * 1000.0
                    _dispatch_record_step(
                        session_id=session_id,
                        step_index=step_idx,
                        step_type="thought",
                        agent_name=agent_name,
                        input_data=input_str,
                        output_data=f"Error: {type(exc).__name__}: {exc}",
                        latency_ms=round(latency, 2),
                    )
                    raise
                finally:
                    reset_current_agent(token)

            return sync_wrapper

    if callable(name_or_func):
        return decorator(name_or_func)
    return decorator


def trace_mcp(name_or_func: Any = None, *, name: str | None = None) -> Any:
    """Decorator to trace tool execution or custom MCP calls."""

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        tool_name = name or (name_or_func if isinstance(name_or_func, str) else None) or fn.__name__

        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                session_id = get_current_session_id()
                if session_id is None:
                    return await fn(*args, **kwargs)

                agent_name = get_current_agent()
                start_time = time.perf_counter()
                input_str = _format_input(tool_name, args, kwargs, kind="tool")
                step_idx = next_step_index()
                try:
                    result = await fn(*args, **kwargs)
                    latency = (time.perf_counter() - start_time) * 1000.0
                    await _dispatch_record_step_async(
                        session_id=session_id,
                        step_index=step_idx,
                        step_type="tool_call",
                        agent_name=agent_name,
                        input_data=input_str,
                        output_data=_format_output(result),
                        latency_ms=round(latency, 2),
                    )
                    return result
                except Exception as exc:
                    latency = (time.perf_counter() - start_time) * 1000.0
                    await _dispatch_record_step_async(
                        session_id=session_id,
                        step_index=step_idx,
                        step_type="tool_call",
                        agent_name=agent_name,
                        input_data=input_str,
                        output_data=f"Error: {type(exc).__name__}: {exc}",
                        latency_ms=round(latency, 2),
                    )
                    raise

            return async_wrapper
        else:

            @functools.wraps(fn)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                session_id = get_current_session_id()
                if session_id is None:
                    return fn(*args, **kwargs)

                agent_name = get_current_agent()
                start_time = time.perf_counter()
                input_str = _format_input(tool_name, args, kwargs, kind="tool")
                step_idx = next_step_index()
                try:
                    result = fn(*args, **kwargs)
                    latency = (time.perf_counter() - start_time) * 1000.0
                    _dispatch_record_step(
                        session_id=session_id,
                        step_index=step_idx,
                        step_type="tool_call",
                        agent_name=agent_name,
                        input_data=input_str,
                        output_data=_format_output(result),
                        latency_ms=round(latency, 2),
                    )
                    return result
                except Exception as exc:
                    latency = (time.perf_counter() - start_time) * 1000.0
                    _dispatch_record_step(
                        session_id=session_id,
                        step_index=step_idx,
                        step_type="tool_call",
                        agent_name=agent_name,
                        input_data=input_str,
                        output_data=f"Error: {type(exc).__name__}: {exc}",
                        latency_ms=round(latency, 2),
                    )
                    raise

            return sync_wrapper

    if callable(name_or_func):
        return decorator(name_or_func)
    return decorator
