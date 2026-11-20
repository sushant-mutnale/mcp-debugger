import asyncio
import pytest

from mcp_debugger.sdk import (
    get_current_agent,
    get_current_session_id,
    set_active_session,
    trace_agent,
    trace_mcp,
)


class MockBackend:
    def __init__(self) -> None:
        self.steps: list[dict] = []

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
    ) -> int:
        step = {
            "id": len(self.steps) + 1,
            "session_id": session_id,
            "step_index": step_index,
            "step_type": step_type,
            "agent_name": agent_name,
            "input": input_data,
            "output": output_data,
            "latency_ms": latency_ms,
            "tokens_input": tokens_input,
            "tokens_output": tokens_output,
        }
        self.steps.append(step)
        return step["id"]


def test_safe_fallback_when_no_session() -> None:
    """Decorators execute transparently when no session is active."""
    set_active_session(None, None)
    assert get_current_session_id() is None
    assert get_current_agent() is None

    @trace_agent("noop_agent")
    def add(a: int, b: int) -> int:
        return a + b

    @trace_mcp("noop_tool")
    def multiply(a: int, b: int) -> int:
        return a * b

    assert add(2, 3) == 5
    assert multiply(4, 5) == 20


def test_trace_agent_sync_success() -> None:
    """Sync agent function records input, output, latency, and agent context."""
    backend = MockBackend()
    set_active_session(101, backend)

    @trace_agent("planner")
    def plan(task: str, priority: int = 1) -> str:
        assert get_current_agent() == "planner"
        return f"Plan for {task} (priority {priority})"

    result = plan("Refactor architecture", priority=2)
    assert result == "Plan for Refactor architecture (priority 2)"
    assert get_current_agent() is None

    assert len(backend.steps) == 1
    step = backend.steps[0]
    assert step["session_id"] == 101
    assert step["step_index"] == 0
    assert step["agent_name"] == "planner"
    assert "Refactor architecture" in step["input"]
    assert "priority 2" in step["output"]
    assert step["latency_ms"] >= 0.0


@pytest.mark.asyncio
async def test_trace_agent_async_success() -> None:
    """Async agent function records input, output, latency, and agent context."""
    backend = MockBackend()
    set_active_session(102, backend)

    @trace_agent(name="async_researcher")
    async def research(query: str) -> dict:
        await asyncio.sleep(0.01)
        assert get_current_agent() == "async_researcher"
        return {"query": query, "found": 3}

    res = await research("stateless mcp")
    assert res == {"query": "stateless mcp", "found": 3}
    assert get_current_agent() is None

    assert len(backend.steps) == 1
    step = backend.steps[0]
    assert step["session_id"] == 102
    assert step["agent_name"] == "async_researcher"
    assert "stateless mcp" in step["input"]
    assert step["latency_ms"] >= 10.0


def test_trace_agent_exception() -> None:
    """Agent records exception and re-raises original error."""
    backend = MockBackend()
    set_active_session(103, backend)

    @trace_agent("faulty_agent")
    def fail(msg: str) -> None:
        raise ValueError(f"Crash: {msg}")

    with pytest.raises(ValueError, match="Crash: fatal"):
        fail("fatal")

    assert get_current_agent() is None
    assert len(backend.steps) == 1
    step = backend.steps[0]
    assert step["session_id"] == 103
    assert step["agent_name"] == "faulty_agent"
    assert "error" in step["output"].lower() or "crash" in step["output"].lower()


@pytest.mark.asyncio
async def test_nested_agent_and_mcp_tool_call() -> None:
    """Nested @trace_mcp inside @trace_agent inherits agent context and records tool_call."""
    backend = MockBackend()
    set_active_session(104, backend)

    @trace_mcp("fetch_weather")
    async def get_weather(city: str) -> str:
        assert get_current_agent() == "weather_bot"
        return f"Sunny in {city}"

    @trace_agent("weather_bot")
    async def run_bot(city: str) -> str:
        weather = await get_weather(city)
        return f"Report: {weather}"

    final_report = await run_bot("Tokyo")
    assert final_report == "Report: Sunny in Tokyo"

    # Expect 2 steps: step 0 (tool_call fetch_weather), step 1 (agent thought / run)
    assert len(backend.steps) == 2
    tool_step = backend.steps[0]
    agent_step = backend.steps[1]

    assert tool_step["step_type"] == "tool_call"
    assert tool_step["agent_name"] == "weather_bot"
    assert "fetch_weather" in tool_step["input"]
    assert "Tokyo" in tool_step["input"]
    assert "Sunny in Tokyo" in tool_step["output"]

    assert agent_step["agent_name"] == "weather_bot"
    assert "Report: Sunny in Tokyo" in agent_step["output"]


def test_decorator_bare_no_args() -> None:
    """Decorators work when used without parentheses."""
    backend = MockBackend()
    set_active_session(105, backend)

    @trace_agent
    def helper_agent(x: int) -> int:
        return x * 2

    @trace_mcp
    def helper_tool(x: int) -> int:
        return x + 1

    assert helper_agent(5) == 10
    assert helper_tool(5) == 6

    assert len(backend.steps) == 2
    assert backend.steps[0]["agent_name"] == "helper_agent"
    assert backend.steps[1]["step_type"] == "tool_call"
    assert "helper_tool" in backend.steps[1]["input"]


def test_trace_mcp_sync_and_exception() -> None:
    """Sync @trace_mcp handles exceptions and records them properly."""
    backend = MockBackend()
    set_active_session(106, backend)

    @trace_mcp("calculator")
    def divide(a: int, b: int) -> float:
        return a / b

    assert divide(10, 2) == 5.0
    assert len(backend.steps) == 1
    assert backend.steps[0]["output"] == "5.0"

    with pytest.raises(ZeroDivisionError):
        divide(10, 0)

    assert len(backend.steps) == 2
    assert "ZeroDivisionError" in backend.steps[1]["output"]


@pytest.mark.asyncio
async def test_trace_mcp_async_exception() -> None:
    """Async @trace_mcp handles exceptions and records them properly."""
    backend = MockBackend()
    set_active_session(107, backend)

    @trace_mcp("remote_api")
    async def fetch_data() -> str:
        await asyncio.sleep(0.005)
        raise ConnectionResetError("Connection dropped")

    with pytest.raises(ConnectionResetError, match="Connection dropped"):
        await fetch_data()

    assert len(backend.steps) == 1
    assert "ConnectionResetError" in backend.steps[0]["output"]


@pytest.mark.asyncio
async def test_async_backend_coroutine_dispatch() -> None:
    """Backend whose record_step is an async coroutine is awaited/scheduled."""
    steps = []

    class AsyncBackend:
        async def record_step(self, **kwargs) -> int:
            await asyncio.sleep(0.001)
            steps.append(kwargs)
            return len(steps)

    set_active_session(108, AsyncBackend())

    @trace_agent("async_worker")
    async def do_work() -> str:
        return "done"

    res = await do_work()
    assert res == "done"
    # Wait tiny amount for background task
    await asyncio.sleep(0.01)
    assert len(steps) == 1
    assert steps[0]["agent_name"] == "async_worker"

