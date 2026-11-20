"""Live LLM counterfactual replay engine for step attribution (--live)."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from mcp_debugger.attribution.ablation import AblationEngine
from mcp_debugger.attribution.classifier import FailureClassifier
from mcp_debugger.attribution.models import (
    LiveCounterfactualResult,
    PerturbationType,
    PreflightEstimate,
)


class LiveCounterfactualEngine:
    """Live LLM counterfactual replay engine (--live).

    Re-executes downstream trajectory steps live against an LLM client
    from a perturbed candidate step, guarded by pre-flight token estimation,
    step ceilings, and execution timeouts.
    """

    def __init__(
        self,
        classifier: FailureClassifier | None = None,
        ablation_engine: AblationEngine | None = None,
        llm_client: Any = None,
        max_steps: int = 5,
        timeout_seconds: float = 30.0,
        cost_per_1k_tokens: float = 0.005,
    ) -> None:
        self.classifier = classifier or FailureClassifier()
        self.ablation_engine = ablation_engine or AblationEngine(classifier=self.classifier)
        self.llm_client = llm_client
        self.max_steps = max_steps
        self.timeout_seconds = timeout_seconds
        self.cost_per_1k_tokens = cost_per_1k_tokens

    def estimate_preflight(
        self,
        steps: list[dict[str, Any]],
        candidate_step_index: int,
        max_steps: int | None = None,
    ) -> PreflightEstimate:
        """Calculate token heuristics and estimated cost before initiating live LLM calls."""
        limit = max_steps if max_steps is not None else self.max_steps

        # Sum characters in prefix context up to candidate step
        prefix_chars = 0
        for s in steps:
            if s.get("step_index", 0) <= candidate_step_index:
                prefix_chars += len(str(s.get("input", "")))
                prefix_chars += len(str(s.get("output", "")))

        # Standard heuristic: ~4 characters per token
        prefix_tokens = max(10, prefix_chars // 4)
        projected_tokens = limit * 200
        total_estimated_tokens = prefix_tokens + projected_tokens
        estimated_cost = (total_estimated_tokens / 1000.0) * self.cost_per_1k_tokens

        warning_message = (
            f"Pre-flight estimate: Running live replay from step {candidate_step_index} "
            f"will generate up to {limit} steps, estimating ~{total_estimated_tokens} tokens "
            f"(~${estimated_cost:.4f} USD)."
        )

        return PreflightEstimate(
            candidate_step_index=candidate_step_index,
            estimated_tokens=total_estimated_tokens,
            estimated_cost_usd=round(estimated_cost, 6),
            max_downstream_steps=limit,
            warning_message=warning_message,
        )

    async def run_live_ablation(
        self,
        session_id: int,
        steps: list[dict[str, Any]],
        candidate_step_index: int,
        perturbation: PerturbationType | str = PerturbationType.TOOL_ERROR,
        messages: list[dict[str, Any]] | None = None,
    ) -> LiveCounterfactualResult:
        """Run opt-in live counterfactual re-execution from the perturbed step."""
        preflight = self.estimate_preflight(steps=steps, candidate_step_index=candidate_step_index)

        original_diagnosis = self.classifier.classify_session(
            session_id=session_id, messages=messages, steps=steps
        )

        # Perturb the candidate step in the trajectory
        perturbed_all = self.ablation_engine.ablate_step(
            steps=steps,
            step_index=candidate_step_index,
            perturbation=perturbation,
        )

        # Truncate downstream: live replay re-generates steps from the perturbation onward
        prefix_steps = [
            s for s in perturbed_all if s.get("step_index", 0) <= candidate_step_index
        ]

        # Prepare prompt dialogue context for the LLM
        prompt_messages: list[dict[str, str]] = [
            {
                "role": "system",
                "content": (
                    "You are an AI assistant executing a task. The previous execution steps "
                    "are recorded below. Continue the execution to complete the goal."
                ),
            }
        ]

        for s in prefix_steps:
            stype = s.get("step_type", "thought")
            if stype == "thought":
                prompt_messages.append({"role": "assistant", "content": str(s.get("output", ""))})
            elif stype == "tool_call":
                prompt_messages.append(
                    {"role": "assistant", "content": f"Tool call: {s.get('input', '')}"}
                )
                prompt_messages.append(
                    {"role": "tool", "content": str(s.get("output", ""))}
                )

        generated_steps: list[dict[str, Any]] = []
        guardrail_triggered: str | None = None
        start_time = time.monotonic()
        tokens_used = preflight.estimated_tokens // 2

        if self.llm_client is not None:
            while len(generated_steps) < self.max_steps:
                elapsed = time.monotonic() - start_time
                remaining_timeout = self.timeout_seconds - elapsed

                if remaining_timeout <= 0:
                    guardrail_triggered = "timeout_exceeded"
                    break

                try:
                    # Async generation with timeout enforcement
                    if asyncio.iscoroutinefunction(self.llm_client.generate):
                        resp = await asyncio.wait_for(
                            self.llm_client.generate(prompt_messages),
                            timeout=remaining_timeout,
                        )
                    else:
                        resp = await asyncio.wait_for(
                            asyncio.to_thread(self.llm_client.generate, prompt_messages),
                            timeout=remaining_timeout,
                        )
                except (asyncio.TimeoutError, TimeoutError):
                    guardrail_triggered = "timeout_exceeded"
                    break
                except Exception as e:
                    guardrail_triggered = f"client_error: {e}"
                    break

                # Parse response into a trajectory step
                next_index = candidate_step_index + len(generated_steps) + 1
                is_tool_request = False
                parsed_dict: Any = None

                if isinstance(resp, str):
                    try:
                        parsed_dict = json.loads(resp)
                    except Exception:
                        pass
                elif isinstance(resp, dict):
                    parsed_dict = resp

                if isinstance(parsed_dict, dict) and (
                    "tool" in parsed_dict or "name" in parsed_dict
                ):
                    is_tool_request = True
                    new_step = {
                        "id": 1000 + next_index,
                        "step_index": next_index,
                        "step_type": "tool_call",
                        "agent_name": prefix_steps[-1].get("agent_name", "agent"),
                        "input": json.dumps(parsed_dict)
                        if not isinstance(resp, str)
                        else resp,
                        "output": json.dumps({"status": "simulated_ok"}),
                    }
                else:
                    new_step = {
                        "id": 1000 + next_index,
                        "step_index": next_index,
                        "step_type": "thought",
                        "agent_name": prefix_steps[-1].get("agent_name", "agent"),
                        "input": "Continue task",
                        "output": str(resp),
                    }

                generated_steps.append(new_step)
                prompt_messages.append({"role": "assistant", "content": str(resp)})

                # If the agent reached a conclusion or non-tool completion thought, stop
                if not is_tool_request:
                    break

            if len(generated_steps) >= self.max_steps and guardrail_triggered is None:
                guardrail_triggered = "max_steps_exceeded"

        counterfactual_steps = prefix_steps + generated_steps

        counterfactual_diagnosis = self.classifier.classify_session(
            session_id=session_id, messages=messages, steps=counterfactual_steps
        )

        outcome_changed = (
            counterfactual_diagnosis.category != original_diagnosis.category
            or (
                original_diagnosis.details.get("loop_detected")
                and not counterfactual_diagnosis.details.get("loop_detected")
            )
            or (
                original_diagnosis.details.get("empty_result_trap")
                and not counterfactual_diagnosis.details.get("empty_result_trap")
            )
        )

        return LiveCounterfactualResult(
            candidate_step_index=candidate_step_index,
            perturbation=perturbation,
            preflight=preflight,
            original_diagnosis=original_diagnosis,
            counterfactual_diagnosis=counterfactual_diagnosis,
            counterfactual_steps=counterfactual_steps,
            tokens_used=tokens_used,
            outcome_changed=outcome_changed,
            guardrail_triggered=guardrail_triggered,
        )
