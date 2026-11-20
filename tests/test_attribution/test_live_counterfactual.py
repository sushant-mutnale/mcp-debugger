"""Unit tests for live LLM counterfactual replay engine (--live)."""

import asyncio
import json
import pytest

from mcp_debugger.attribution.live import LiveCounterfactualEngine, PreflightEstimate
from mcp_debugger.attribution.models import FailureCategory, PerturbationType


class MockLLMClient:
    """Mock LLM client for testing live counterfactual replay."""

    def __init__(self, responses: list[str] | None = None, delay: float = 0.0) -> None:
        self.responses = responses or ["I will now use an alternative approach without looping."]
        self.call_count = 0
        self.delay = delay

    async def generate(self, messages: list[dict[str, str]]) -> str:
        if self.delay > 0:
            await asyncio.sleep(self.delay)
        response = self.responses[min(self.call_count, len(self.responses) - 1)]
        self.call_count += 1
        return response


def test_preflight_estimation() -> None:
    """Pre-flight estimator accurately calculates token heuristics and cost."""
    engine = LiveCounterfactualEngine(max_steps=5)

    steps = [
        {"step_index": 0, "step_type": "thought", "output": "A" * 400},
        {"step_index": 1, "step_type": "tool_call", "output": "B" * 400},
        {"step_index": 2, "step_type": "tool_call", "output": "C" * 400},
    ]

    estimate = engine.estimate_preflight(steps=steps, candidate_step_index=1)
    assert isinstance(estimate, PreflightEstimate)
    assert estimate.candidate_step_index == 1
    assert estimate.estimated_tokens > 0
    assert estimate.estimated_cost_usd >= 0.0
    assert "pre-flight" in estimate.warning_message.lower()


@pytest.mark.asyncio
async def test_live_counterfactual_runner_success() -> None:
    """Live counterfactual runner executes mock LLM from perturbed step and resolves failure."""
    mock_llm = MockLLMClient(
        responses=[
            "I noticed the tool returned an error. I will handle it gracefully and finish task.",
        ]
    )
    engine = LiveCounterfactualEngine(llm_client=mock_llm, max_steps=3)

    steps = [
        {
            "id": 1,
            "step_index": 0,
            "step_type": "thought",
            "agent_name": "coder",
            "input": "Check file",
            "output": "Checking",
        },
        {
            "id": 2,
            "step_index": 1,
            "step_type": "tool_call",
            "agent_name": "coder",
            "input": json.dumps({"tool": "read_file", "args": ["data.txt"]}),
            "output": "File not ready",
        },
        {
            "id": 3,
            "step_index": 2,
            "step_type": "tool_call",
            "agent_name": "coder",
            "input": json.dumps({"tool": "read_file", "args": ["data.txt"]}),
            "output": "File not ready",
        },
        {
            "id": 4,
            "step_index": 3,
            "step_type": "tool_call",
            "agent_name": "coder",
            "input": json.dumps({"tool": "read_file", "args": ["data.txt"]}),
            "output": "File not ready",
        },
    ]

    result = await engine.run_live_ablation(
        session_id=30,
        steps=steps,
        candidate_step_index=1,
        perturbation=PerturbationType.TOOL_ERROR,
    )

    assert result.original_diagnosis.category == FailureCategory.AGENT
    assert result.outcome_changed is True
    assert len(result.counterfactual_steps) > 2
    assert mock_llm.call_count >= 1


@pytest.mark.asyncio
async def test_guardrail_max_steps_enforced() -> None:
    """Live runner terminates downstream generation when max_steps limit is hit."""
    # LLM always produces another tool call request
    mock_llm = MockLLMClient(
        responses=[
            json.dumps({"thought": "continue", "tool": "step_tool"}),
        ]
    )
    max_steps_limit = 2
    engine = LiveCounterfactualEngine(llm_client=mock_llm, max_steps=max_steps_limit)

    steps = [
        {
            "id": 1,
            "step_index": 0,
            "step_type": "tool_call",
            "agent_name": "bot",
            "input": json.dumps({"tool": "start"}),
            "output": "started",
        },
    ]

    result = await engine.run_live_ablation(
        session_id=31,
        steps=steps,
        candidate_step_index=0,
        perturbation=PerturbationType.TOOL_ERROR,
    )

    assert result.guardrail_triggered == "max_steps_exceeded"
    # Ensure generated new steps do not exceed max_steps_limit
    new_steps = [s for s in result.counterfactual_steps if s.get("step_index", 0) > 0]
    assert len(new_steps) <= max_steps_limit


@pytest.mark.asyncio
async def test_guardrail_timeout_enforced() -> None:
    """Live runner stops and flags timeout when LLM client hangs or exceeds timeout_seconds."""
    mock_llm = MockLLMClient(delay=1.0)
    engine = LiveCounterfactualEngine(llm_client=mock_llm, timeout_seconds=0.1)

    steps = [
        {
            "id": 1,
            "step_index": 0,
            "step_type": "tool_call",
            "agent_name": "bot",
            "input": json.dumps({"tool": "ping"}),
            "output": "pong",
        },
    ]

    result = await engine.run_live_ablation(
        session_id=32,
        steps=steps,
        candidate_step_index=0,
        perturbation=PerturbationType.TOOL_ERROR,
    )

    assert result.guardrail_triggered == "timeout_exceeded"
