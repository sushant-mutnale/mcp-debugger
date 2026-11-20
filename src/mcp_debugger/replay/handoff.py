"""Cassette-backed handoff replay engine."""

from __future__ import annotations

from dataclasses import dataclass, field
import inspect
import json
from typing import Any, Callable

from mcp_debugger.replay.diff import DiffNode, compare_json
from mcp_debugger.storage.database import Database


@dataclass
class HandoffReplayResult:
    session_id: int
    handoff_step_index: int
    from_agent: str
    to_agent: str
    upstream_steps_count: int
    upstream_cost_saved: bool = True
    downstream_original_steps: list[dict[str, Any]] = field(default_factory=list)
    downstream_replayed_steps: list[dict[str, Any]] | None = None
    diff: DiffNode | None = None
    divergence_detected: bool = False
    replayed_output: Any = None


class HandoffReplayEngine:
    """Engine for cassette-backed handoff replay and downstream ablation."""

    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path

    async def load_handoff_cassette(
        self,
        session_id: int,
        handoff_step_index: int | None = None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
        """Load cassette steps and partition into upstream, handoff, and downstream."""
        db = Database(db_path=self.db_path)
        await db.connect()
        try:
            steps = await db.get_steps(session_id)
        finally:
            await db.close()

        if not steps:
            raise ValueError(f"No steps found for session {session_id}")

        handoff_step = None
        if handoff_step_index is not None:
            for s in steps:
                if s["step_index"] == handoff_step_index:
                    handoff_step = s
                    break
            if handoff_step is None:
                raise ValueError(
                    f"Handoff step with index {handoff_step_index} not found for session {session_id}"
                )
        else:
            for s in steps:
                if s.get("step_type") == "handoff":
                    handoff_step = s
                    break
            if handoff_step is None:
                raise ValueError(f"No handoff step found for session {session_id}")

        target_idx = handoff_step["step_index"]
        upstream = [s for s in steps if s["step_index"] <= target_idx]
        downstream = [s for s in steps if s["step_index"] > target_idx]

        return handoff_step, upstream, downstream

    async def replay_from_handoff(
        self,
        session_id: int,
        downstream_agent_callable: Callable[..., Any],
        handoff_step_index: int | None = None,
        override_context: Any = None,
    ) -> HandoffReplayResult:
        """Replay downstream execution starting from the recorded handoff cassette."""
        handoff_step, upstream, downstream = await self.load_handoff_cassette(
            session_id, handoff_step_index
        )

        input_payload: dict[str, Any] = {}
        raw_input = handoff_step.get("input") or handoff_step.get("input_data")
        if isinstance(raw_input, str):
            try:
                input_payload = json.loads(raw_input)
            except Exception:
                input_payload = {}
        elif isinstance(raw_input, dict):
            input_payload = raw_input

        output_payload: dict[str, Any] = {}
        raw_output = handoff_step.get("output") or handoff_step.get("output_data")
        if isinstance(raw_output, str):
            try:
                output_payload = json.loads(raw_output)
            except Exception:
                output_payload = {}
        elif isinstance(raw_output, dict):
            output_payload = raw_output

        from_agent = input_payload.get("from_agent") or handoff_step.get("agent_name") or "unknown"
        to_agent = input_payload.get("to_agent") or output_payload.get("to_agent") or "unknown"

        if override_context is not None:
            context = override_context
        else:
            context = input_payload.get("transferred_context", {})

        if inspect.iscoroutinefunction(downstream_agent_callable):
            replayed_output = await downstream_agent_callable(context)
        else:
            replayed_output = downstream_agent_callable(context)

        # Baseline output calculation: last downstream step's output, or handoff output
        baseline_output = None
        if downstream:
            last_step = downstream[-1]
            raw_last = last_step.get("output") or last_step.get("output_data")
            if isinstance(raw_last, str):
                try:
                    baseline_output = json.loads(raw_last)
                except Exception:
                    baseline_output = raw_last
            else:
                baseline_output = raw_last
        elif "output_context" in output_payload:
            baseline_output = output_payload["output_context"]

        diff = compare_json(baseline_output, replayed_output)
        divergence = diff is not None

        return HandoffReplayResult(
            session_id=session_id,
            handoff_step_index=handoff_step["step_index"],
            from_agent=from_agent,
            to_agent=to_agent,
            upstream_steps_count=len(upstream),
            upstream_cost_saved=True,
            downstream_original_steps=downstream,
            diff=diff,
            divergence_detected=divergence,
            replayed_output=replayed_output,
        )
