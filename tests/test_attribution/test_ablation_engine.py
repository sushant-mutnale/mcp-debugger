"""Unit tests for counterfactual step ablation engine."""

import json

from mcp_debugger.attribution.ablation import AblationEngine
from mcp_debugger.attribution.models import (
    AttributionReport,
    FailureCategory,
    PerturbationType,
    PointOfCommitment,
)


def test_ablate_step_empty_result() -> None:
    """Verifies that ablate_step creates a new steps list with empty_result perturbation."""
    engine = AblationEngine()

    original_steps = [
        {"step_index": 0, "step_type": "thought", "output": "thinking"},
        {"step_index": 1, "step_type": "tool_call", "output": "valid output"},
    ]

    ablated = engine.ablate_step(original_steps, step_index=1, perturbation=PerturbationType.EMPTY_RESULT)

    # Original unchanged
    assert original_steps[1]["output"] == "valid output"
    # Ablated step has empty content
    parsed = json.loads(ablated[1]["output"])
    assert parsed == {"content": []}


def test_ablate_step_tool_error() -> None:
    """Verifies that ablate_step creates a new steps list with tool_error perturbation."""
    engine = AblationEngine()

    original_steps = [
        {"step_index": 0, "step_type": "thought", "output": "thinking"},
        {"step_index": 1, "step_type": "tool_call", "output": "valid output"},
    ]

    ablated = engine.ablate_step(original_steps, step_index=1, perturbation=PerturbationType.TOOL_ERROR)

    parsed = json.loads(ablated[1]["output"])
    assert parsed.get("isError") is True
    assert "content" in parsed


def test_isolate_point_of_commitment_in_loop() -> None:
    """Ablation engine isolates the Point of Commitment (PoC) when an agent loops."""
    engine = AblationEngine()

    steps = [
        {
            "id": 1,
            "step_index": 0,
            "step_type": "thought",
            "agent_name": "coder",
            "input": "Check file status",
            "output": "Starting check",
        },
        {
            "id": 2,
            "step_index": 1,
            "step_type": "tool_call",
            "agent_name": "coder",
            "input": json.dumps({"tool": "read_file", "args": ["data.txt"]}),
            "output": "Not ready",
        },
        {
            "id": 3,
            "step_index": 2,
            "step_type": "tool_call",
            "agent_name": "coder",
            "input": json.dumps({"tool": "read_file", "args": ["data.txt"]}),
            "output": "Not ready",
        },
        {
            "id": 4,
            "step_index": 3,
            "step_type": "tool_call",
            "agent_name": "coder",
            "input": json.dumps({"tool": "read_file", "args": ["data.txt"]}),
            "output": "Not ready",
        },
    ]

    report = engine.run_attribution(session_id=20, steps=steps, perturbation=PerturbationType.TOOL_ERROR)

    assert isinstance(report, AttributionReport)
    assert report.original_diagnosis.category == FailureCategory.AGENT
    assert report.point_of_commitment is not None
    assert isinstance(report.point_of_commitment, PointOfCommitment)
    # PoC is step 1, the earliest step whose ablation breaks the loop
    assert report.point_of_commitment.step_index == 1
    assert report.point_of_commitment.tool_name == "read_file"
    assert len(report.ablation_results) > 0


def test_isolate_point_of_commitment_in_multi_step_cascade() -> None:
    """Identifies the root trigger step in a multi-step failure cascade."""
    engine = AblationEngine()

    steps = [
        {
            "id": 1,
            "step_index": 0,
            "step_type": "thought",
            "agent_name": "researcher",
            "input": "Begin task",
            "output": "Starting search",
        },
        {
            "id": 2,
            "step_index": 1,
            "step_type": "tool_call",
            "agent_name": "researcher",
            "input": json.dumps({"tool": "check_status", "args": {}}),
            "output": json.dumps({"status": "ok"}),
        },
        {
            "id": 3,
            "step_index": 2,
            "step_type": "tool_call",
            "agent_name": "researcher",
            "input": json.dumps({"tool": "fetch_records", "args": {"limit": 10}}),
            "output": json.dumps({"content": []}),  # Empty result trap
        },
        {
            "id": 4,
            "step_index": 3,
            "step_type": "thought",
            "agent_name": "researcher",
            "input": "Process records",
            "output": "Error: IndexError: list index out of range",
        },
    ]

    report = engine.run_attribution(session_id=21, steps=steps, perturbation=PerturbationType.TOOL_ERROR)

    assert report.original_diagnosis.category == FailureCategory.TOOL
    assert report.original_diagnosis.details.get("empty_result_trap") is True
    assert report.point_of_commitment is not None
    # Step 1 was ok, Step 2 was the empty result trap
    assert report.point_of_commitment.step_index == 2
    assert report.point_of_commitment.tool_name == "fetch_records"


def test_clean_session_has_no_poc() -> None:
    """Clean sessions without failures have point_of_commitment as None."""
    engine = AblationEngine()

    steps = [
        {
            "id": 1,
            "step_index": 0,
            "step_type": "thought",
            "agent_name": "worker",
            "input": "Run task",
            "output": "Done",
        },
        {
            "id": 2,
            "step_index": 1,
            "step_type": "tool_call",
            "agent_name": "worker",
            "input": json.dumps({"tool": "ping", "args": {}}),
            "output": "pong",
        },
    ]

    report = engine.run_attribution(session_id=22, steps=steps)
    assert report.original_diagnosis.category == FailureCategory.NONE
    assert report.point_of_commitment is None
    assert report.ablation_results == []


def test_custom_payload_ablation() -> None:
    """Ablate step with custom perturbation payload."""
    engine = AblationEngine()

    steps = [
        {"step_index": 0, "step_type": "tool_call", "output": "old"},
    ]

    ablated = engine.ablate_step(
        steps,
        step_index=0,
        perturbation=PerturbationType.CUSTOM,
        custom_payload={"status": "mocked", "content": [{"text": "custom"}]},
    )

    parsed = json.loads(ablated[0]["output"])
    assert parsed.get("status") == "mocked"


def test_candidate_step_indices_filtering() -> None:
    """Custom candidate_step_indices only runs ablation on specified steps."""
    engine = AblationEngine()

    steps = [
        {
            "id": 1,
            "step_index": 0,
            "step_type": "tool_call",
            "input": json.dumps({"tool": "ping", "args": {}}),
            "output": "pong",
        },
        {
            "id": 2,
            "step_index": 1,
            "step_type": "tool_call",
            "input": json.dumps({"tool": "ping", "args": {}}),
            "output": "pong",
        },
        {
            "id": 3,
            "step_index": 2,
            "step_type": "tool_call",
            "input": json.dumps({"tool": "ping", "args": {}}),
            "output": "pong",
        },
    ]

    # Only test step_index 1
    report = engine.run_attribution(
        session_id=23,
        steps=steps,
        perturbation=PerturbationType.TOOL_ERROR,
        candidate_step_indices=[1],
    )
    assert len(report.ablation_results) == 1
    assert report.ablation_results[0].step_index == 1
    assert report.point_of_commitment is not None
    assert report.point_of_commitment.step_index == 1

