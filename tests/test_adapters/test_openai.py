import pytest

from mcp_debugger.adapters.openai import (
    OpenAIAgentTracker,
    trace_openai_agent,
)
from mcp_debugger.sdk import set_active_session


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


def test_tracker_records_llm_tool_and_handoff() -> None:
    """OpenAIAgentTracker properly records LLM calls, tool executions, and agent handoffs."""
    backend = MockBackend()
    set_active_session(201, backend)

    tracker = OpenAIAgentTracker(agent_name="triage_agent")

    # 1. Model call
    tracker.on_llm_start(model="gpt-4o", prompt="User: Help with billing")
    tracker.on_llm_end(
        response="Transferring to billing agent",
        usage={"prompt_tokens": 25, "completion_tokens": 10},
    )

    # 2. Tool call
    tracker.on_tool_start(tool_name="lookup_customer", arguments={"email": "alice@example.com"})
    tracker.on_tool_end(tool_name="lookup_customer", result={"tier": "enterprise"})

    # 3. Agent handoff
    tracker.on_handoff(target_agent="billing_agent", context={"reason": "upgrade enquiry"})

    steps = backend.steps
    assert len(steps) == 3

    # Step 0: LLM call
    assert steps[0]["step_type"] == "llm_call"
    assert steps[0]["agent_name"] == "triage_agent"
    assert "Help with billing" in steps[0]["input"]
    assert "Transferring to billing" in steps[0]["output"]
    assert steps[0]["tokens_input"] == 25
    assert steps[0]["tokens_output"] == 10

    # Step 1: Tool call
    assert steps[1]["step_type"] == "tool_call"
    assert steps[1]["agent_name"] == "triage_agent"
    assert "lookup_customer" in steps[1]["input"]
    assert "enterprise" in steps[1]["output"]

    # Step 2: Handoff
    assert steps[2]["step_type"] == "handoff"
    assert steps[2]["agent_name"] == "triage_agent"
    assert "billing_agent" in steps[2]["output"]


def test_trace_openai_agent_wrapper() -> None:
    """trace_openai_agent wraps agent or runner and captures executions."""
    backend = MockBackend()
    set_active_session(202, backend)

    class MockAgent:
        def __init__(self, name: str) -> None:
            self.name = name

        def run(self, prompt: str) -> str:
            return f"{self.name} response to {prompt}"

    raw_agent = MockAgent(name="support_bot")
    wrapped_agent = trace_openai_agent(raw_agent)

    res = wrapped_agent.run("Reset password")
    assert res == "support_bot response to Reset password"

    assert len(backend.steps) == 1
    step = backend.steps[0]
    assert step["session_id"] == 202
    assert step["agent_name"] == "support_bot"
    assert "Reset password" in step["input"]
    assert "support_bot response" in step["output"]


def test_trace_openai_agent_exception() -> None:
    """trace_openai_agent captures errors and re-raises."""
    backend = MockBackend()
    set_active_session(203, backend)

    class FailingAgent:
        def run(self, query: str):
            raise RuntimeError("API quota exceeded")

    agent = trace_openai_agent(FailingAgent())
    with pytest.raises(RuntimeError, match="API quota exceeded"):
        agent.run("test query")

    assert len(backend.steps) == 1
    assert "RuntimeError" in backend.steps[0]["output"]


def test_tracker_noop_when_no_session() -> None:
    """OpenAIAgentTracker methods safely no-op when no session is active."""
    set_active_session(None, None)
    tracker = OpenAIAgentTracker("standalone")
    tracker.on_llm_start("gpt-4", "hello")
    tracker.on_llm_end("hi", usage=None)
    tracker.on_tool_start("search", {"q": "test"})
    tracker.on_tool_end("search", "result")
    tracker.on_handoff("other_agent")

