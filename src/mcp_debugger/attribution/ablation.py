"""Counterfactual step ablation engine for VCR-style replay analysis."""

from __future__ import annotations

import copy
import json
from typing import Any

from mcp_debugger.attribution.classifier import FailureClassifier
from mcp_debugger.attribution.models import (
    AblationResult,
    AttributionReport,
    FailureCategory,
    FailureDiagnosis,
    PerturbationType,
    PointOfCommitment,
)


class AblationEngine:
    """Local counterfactual step ablation engine (VCR Mode).

    Performs fast, deterministic step ablation across candidate steps in a failed trajectory
    without invoking live LLMs, evaluating divergence and isolating the Point of Commitment (PoC).
    """

    def __init__(self, classifier: FailureClassifier | None = None) -> None:
        self.classifier = classifier or FailureClassifier()

    def ablate_step(
        self,
        steps: list[dict[str, Any]],
        step_index: int,
        perturbation: PerturbationType | str = PerturbationType.TOOL_ERROR,
        custom_payload: Any = None,
    ) -> list[dict[str, Any]]:
        """Return a deep copy of steps with the specified step's output perturbed."""
        perturbed_steps = copy.deepcopy(steps)
        perturb_str = str(
            perturbation.value if isinstance(perturbation, PerturbationType) else perturbation
        )

        for step in perturbed_steps:
            if step.get("step_index") == step_index:
                if perturb_str == PerturbationType.EMPTY_RESULT:
                    step["output"] = json.dumps({"content": []})
                elif perturb_str == PerturbationType.TOOL_ERROR:
                    step["output"] = json.dumps(
                        {
                            "isError": True,
                            "content": [{"type": "text", "text": "Ablated error"}],
                        }
                    )
                elif perturb_str == PerturbationType.CUSTOM and custom_payload is not None:
                    if isinstance(custom_payload, str):
                        step["output"] = custom_payload
                    else:
                        step["output"] = json.dumps(custom_payload)
                break

        return perturbed_steps

    def evaluate_ablation(
        self,
        session_id: int,
        steps: list[dict[str, Any]],
        step_index: int,
        perturbation: PerturbationType | str = PerturbationType.TOOL_ERROR,
        messages: list[dict[str, Any]] | None = None,
        custom_payload: Any = None,
        original_diagnosis: FailureDiagnosis | None = None,
    ) -> AblationResult:
        """Run single step ablation, evaluate counterfactual diagnosis, and calculate divergence."""
        if original_diagnosis is None:
            original_diagnosis = self.classifier.classify_session(
                session_id=session_id, messages=messages, steps=steps
            )

        perturbed_steps = self.ablate_step(
            steps=steps,
            step_index=step_index,
            perturbation=perturbation,
            custom_payload=custom_payload,
        )

        counterfactual_diagnosis = self.classifier.classify_session(
            session_id=session_id, messages=messages, steps=perturbed_steps
        )

        # Evaluate if the perturbation broke or altered the failure cascade
        outcome_changed = False
        divergence_score = 0.0

        if counterfactual_diagnosis.category != original_diagnosis.category:
            outcome_changed = True
            divergence_score = 0.8
            if counterfactual_diagnosis.category == FailureCategory.NONE:
                divergence_score = 1.0
        elif (
            counterfactual_diagnosis.root_cause_step_index
            != original_diagnosis.root_cause_step_index
        ):
            outcome_changed = True
            divergence_score = 0.6
        elif (
            original_diagnosis.details.get("empty_result_trap")
            and not counterfactual_diagnosis.details.get("empty_result_trap")
        ):
            outcome_changed = True
            divergence_score = 0.7
        elif (
            original_diagnosis.details.get("loop_detected")
            and not counterfactual_diagnosis.details.get("loop_detected")
        ):
            outcome_changed = True
            divergence_score = 0.7

        return AblationResult(
            step_index=step_index,
            perturbation=perturbation,
            original_diagnosis=original_diagnosis,
            counterfactual_diagnosis=counterfactual_diagnosis,
            outcome_changed=outcome_changed,
            divergence_score=divergence_score,
        )

    def run_attribution(
        self,
        session_id: int,
        steps: list[dict[str, Any]],
        messages: list[dict[str, Any]] | None = None,
        perturbation: PerturbationType | str = PerturbationType.TOOL_ERROR,
        candidate_step_indices: list[int] | None = None,
    ) -> AttributionReport:
        """Evaluate candidate steps and isolate the Point of Commitment (PoC)."""
        original_diagnosis = self.classifier.classify_session(
            session_id=session_id, messages=messages, steps=steps
        )

        if original_diagnosis.category == FailureCategory.NONE:
            return AttributionReport(
                session_id=session_id,
                original_diagnosis=original_diagnosis,
                point_of_commitment=None,
                ablation_results=[],
            )

        # Default candidates to all tool_call steps in chronological order
        if candidate_step_indices is None:
            candidate_step_indices = [
                s.get("step_index", idx)
                for idx, s in enumerate(steps)
                if s.get("step_type") == "tool_call"
            ]

        ablation_results: list[AblationResult] = []
        poc: PointOfCommitment | None = None

        for step_idx in candidate_step_indices:
            res = self.evaluate_ablation(
                session_id=session_id,
                steps=steps,
                step_index=step_idx,
                perturbation=perturbation,
                messages=messages,
                original_diagnosis=original_diagnosis,
            )
            ablation_results.append(res)

            # Earliest step whose ablation breaks the failure cascade is the PoC
            if res.outcome_changed and poc is None:
                target_step = next(
                    (s for s in steps if s.get("step_index") == step_idx), None
                )
                tool_name = None
                agent_name = None
                step_type = "tool_call"
                if target_step:
                    step_type = target_step.get("step_type", "tool_call")
                    agent_name = target_step.get("agent_name")
                    tool_name = self.classifier._extract_tool_name(target_step.get("input"))

                perturb_name = str(
                    perturbation.value
                    if isinstance(perturbation, PerturbationType)
                    else perturbation
                )
                poc = PointOfCommitment(
                    step_index=step_idx,
                    step_type=step_type,
                    agent_name=agent_name,
                    tool_name=tool_name,
                    perturbation=perturbation,
                    description=(
                        f"Perturbing step {step_idx} ({tool_name or step_type}) with "
                        f"{perturb_name} broke the failure cascade "
                        f"({original_diagnosis.category.value} -> "
                        f"{res.counterfactual_diagnosis.category.value})."
                    ),
                )

        return AttributionReport(
            session_id=session_id,
            original_diagnosis=original_diagnosis,
            point_of_commitment=poc,
            ablation_results=ablation_results,
        )
