"""Deterministic heuristic failure classifier and loop detector."""

from __future__ import annotations

import json
from typing import Any

from mcp_debugger.attribution.models import FailureCategory, FailureDiagnosis


class FailureClassifier:
    """Deterministic heuristic failure classifier and loop detector.

    Analyzes messages and trajectory steps to classify root causes across
    agent, tool, and protocol boundaries with sub-millisecond execution.
    """

    def __init__(self, loop_threshold: int = 3) -> None:
        self.loop_threshold = loop_threshold

    def classify_session(
        self,
        session_id: int,
        messages: list[dict[str, Any]] | None = None,
        steps: list[dict[str, Any]] | None = None,
    ) -> FailureDiagnosis:
        """Classify session failure boundary and identify root cause step."""
        # 1. Check protocol-level errors from wire messages
        if messages:
            protocol_diag = self._check_protocol_errors(session_id, messages)
            if protocol_diag is not None:
                return protocol_diag

        # 2. Check steps-based failure indicators
        if steps:
            # Check for empty result traps first (upstream tool flaw trapping downstream agent)
            empty_trap_diag = self._check_empty_result_trap(session_id, steps)
            if empty_trap_diag is not None:
                return empty_trap_diag

            # Check for tool call loops (agent reasoning flaw)
            loop_diag = self._check_tool_loops(session_id, steps)
            if loop_diag is not None:
                return loop_diag

            # Check for direct tool execution errors
            tool_error_diag = self._check_tool_errors(session_id, steps)
            if tool_error_diag is not None:
                return tool_error_diag

        return FailureDiagnosis(
            session_id=session_id,
            category=FailureCategory.NONE,
            root_cause_step_index=None,
            summary="Clean session: no failure or loop patterns detected.",
            details={},
            recommendations=[],
        )

    def _check_protocol_errors(
        self, session_id: int, messages: list[dict[str, Any]]
    ) -> FailureDiagnosis | None:
        for msg in messages:
            error_val = msg.get("error")
            if not error_val:
                continue

            error_obj: dict[str, Any] = {}
            if isinstance(error_val, str):
                try:
                    parsed = json.loads(error_val)
                    if isinstance(parsed, dict):
                        error_obj = parsed
                    else:
                        error_obj = {"message": str(parsed)}
                except Exception:
                    error_obj = {"message": error_val}
            elif isinstance(error_val, dict):
                error_obj = error_val

            code = error_obj.get("code")
            message = error_obj.get("message", "JSON-RPC protocol error")

            return FailureDiagnosis(
                session_id=session_id,
                category=FailureCategory.PROTOCOL,
                root_cause_step_index=None,
                summary=f"Protocol violation: {message}",
                details={
                    "error_code": code,
                    "protocol_error": True,
                    "raw_error": error_obj,
                    "message_id": msg.get("id"),
                },
                recommendations=[
                    "Validate JSON-RPC wire payload against MCP schema specifications.",
                    "Verify client/server capability negotiation and supported methods.",
                ],
            )
        return None

    def _check_empty_result_trap(
        self, session_id: int, steps: list[dict[str, Any]]
    ) -> FailureDiagnosis | None:
        crash_keywords = (
            "error",
            "exception",
            "indexerror",
            "keyerror",
            "typeerror",
            "valueerror",
            "traceback",
            "failed",
        )

        for idx, step in enumerate(steps):
            if step.get("step_type") != "tool_call":
                continue

            output_val = step.get("output", "")
            is_empty = False

            parsed_output: Any = None
            if isinstance(output_val, str):
                output_str = output_val.strip()
                if output_str in ("", "[]", "{}"):
                    is_empty = True
                else:
                    try:
                        parsed_output = json.loads(output_str)
                    except Exception:
                        pass
            elif isinstance(output_val, (dict, list)):
                parsed_output = output_val

            if parsed_output is not None:
                if isinstance(parsed_output, dict):
                    content = parsed_output.get("content")
                    if content == [] or content == "" or not parsed_output:
                        is_empty = True
                elif isinstance(parsed_output, list) and len(parsed_output) == 0:
                    is_empty = True

            if not is_empty:
                continue

            # Look ahead for crash or failure in subsequent steps
            subsequent_crash = False
            crash_reason = ""
            for next_step in steps[idx + 1 :]:
                next_out = str(next_step.get("output", "")).lower()
                next_in = str(next_step.get("input", "")).lower()
                if any(kw in next_out for kw in crash_keywords) or any(
                    kw in next_in for kw in crash_keywords
                ):
                    subsequent_crash = True
                    crash_reason = str(next_step.get("output", ""))
                    break

            if subsequent_crash:
                tool_name = self._extract_tool_name(step.get("input"))
                step_idx = step.get("step_index", idx)
                return FailureDiagnosis(
                    session_id=session_id,
                    category=FailureCategory.TOOL,
                    root_cause_step_index=step_idx,
                    summary=f"Tool '{tool_name}' returned empty result which caused downstream agent failure.",
                    details={
                        "empty_result_trap": True,
                        "tool_name": tool_name,
                        "step_index": step_idx,
                        "downstream_error": crash_reason,
                    },
                    recommendations=[
                        f"Modify tool '{tool_name}' to return explicit empty-state messaging rather than empty payloads.",
                        "Add defensive guards in agent prompt or code to handle empty results without crashing.",
                    ],
                )

        return None

    def _check_tool_loops(
        self, session_id: int, steps: list[dict[str, Any]]
    ) -> FailureDiagnosis | None:
        tool_steps = [s for s in steps if s.get("step_type") == "tool_call"]
        if not tool_steps:
            return None

        # 1. Consecutive identical tool calls
        consecutive_count = 1
        first_step_idx = tool_steps[0].get("step_index", 0)
        prev_signature = self._tool_signature(tool_steps[0].get("input"))
        prev_tool_name = self._extract_tool_name(tool_steps[0].get("input"))
        prev_is_err = self._is_error_output(tool_steps[0].get("output"))

        for i in range(1, len(tool_steps)):
            curr_step = tool_steps[i]
            curr_sig = self._tool_signature(curr_step.get("input"))
            curr_tool = self._extract_tool_name(curr_step.get("input"))
            curr_is_err = self._is_error_output(curr_step.get("output"))

            if (
                curr_sig == prev_signature
                and curr_sig != ("", "")
                and not curr_is_err
                and not prev_is_err
            ):
                consecutive_count += 1
                if consecutive_count >= self.loop_threshold:
                    return FailureDiagnosis(
                        session_id=session_id,
                        category=FailureCategory.AGENT,
                        root_cause_step_index=first_step_idx,
                        summary=f"Agent entered an infinite loop repeatedly calling tool '{prev_tool_name}' ({consecutive_count} times).",
                        details={
                            "loop_detected": True,
                            "tool_name": prev_tool_name,
                            "loop_count": consecutive_count,
                            "root_cause_step_index": first_step_idx,
                        },
                        recommendations=[
                            f"Add loop detection breaker when tool '{prev_tool_name}' fails to change state.",
                            "Inject anti-repetition reflection prompt into agent reasoning context.",
                        ],
                    )
            else:
                consecutive_count = 1
                prev_signature = curr_sig
                prev_tool_name = curr_tool
                prev_is_err = curr_is_err
                first_step_idx = curr_step.get("step_index", i)

        # 2. Cyclic repeating tool call patterns (e.g. A -> B -> A -> B)
        signatures = [self._tool_signature(s.get("input")) for s in tool_steps]
        n = len(signatures)
        for cycle_len in (2, 3):
            if n >= cycle_len * self.loop_threshold:
                pattern = signatures[-cycle_len:]
                repeats = 0
                for k in range(n - cycle_len, -1, -cycle_len):
                    if signatures[k : k + cycle_len] == pattern:
                        repeats += 1
                    else:
                        break
                if repeats >= self.loop_threshold:
                    cycle_tools = [
                        self._extract_tool_name(s.get("input"))
                        for s in tool_steps[-(cycle_len * repeats) : -(cycle_len * (repeats - 1))]
                    ]
                    start_step_idx = tool_steps[-(cycle_len * repeats)].get("step_index", 0)
                    return FailureDiagnosis(
                        session_id=session_id,
                        category=FailureCategory.AGENT,
                        root_cause_step_index=start_step_idx,
                        summary=f"Agent entered cyclic loop alternating between tools ({' -> '.join(cycle_tools)}) {repeats} times.",
                        details={
                            "loop_detected": True,
                            "cycle_detected": True,
                            "tool_name": cycle_tools[0],
                            "loop_count": repeats,
                            "root_cause_step_index": start_step_idx,
                        },
                        recommendations=[
                            "Break cyclic tool alternating pattern by forcing agent to replan or terminate.",
                        ],
                    )

        return None

    def _check_tool_errors(
        self, session_id: int, steps: list[dict[str, Any]]
    ) -> FailureDiagnosis | None:
        for idx, step in enumerate(steps):
            if step.get("step_type") != "tool_call":
                continue

            out = step.get("output")
            has_error = False
            error_msg = ""

            if isinstance(out, dict):
                if out.get("isError") is True:
                    has_error = True
                    error_msg = str(out.get("content", "Tool reported isError=True"))
            elif isinstance(out, str):
                try:
                    parsed = json.loads(out)
                    if isinstance(parsed, dict) and parsed.get("isError") is True:
                        has_error = True
                        error_msg = str(parsed.get("content", "Tool reported isError=True"))
                except Exception:
                    pass

            if has_error:
                tool_name = self._extract_tool_name(step.get("input"))
                step_idx = step.get("step_index", idx)
                return FailureDiagnosis(
                    session_id=session_id,
                    category=FailureCategory.TOOL,
                    root_cause_step_index=step_idx,
                    summary=f"Tool '{tool_name}' failed with execution error: {error_msg}",
                    details={
                        "tool_error": True,
                        "tool_name": tool_name,
                        "step_index": step_idx,
                        "error_message": error_msg,
                    },
                    recommendations=[
                        f"Check tool '{tool_name}' server logs and verify parameter compatibility.",
                    ],
                )
        return None

    def _is_error_output(self, output_val: Any) -> bool:
        if isinstance(output_val, dict):
            return output_val.get("isError") is True
        if isinstance(output_val, str):
            try:
                parsed = json.loads(output_val)
                if isinstance(parsed, dict):
                    return parsed.get("isError") is True
            except Exception:
                pass
        return False

    def _extract_tool_name(self, input_val: Any) -> str:
        if isinstance(input_val, dict):
            return str(input_val.get("tool") or input_val.get("name") or "unknown_tool")
        if isinstance(input_val, str):
            try:
                parsed = json.loads(input_val)
                if isinstance(parsed, dict):
                    return str(parsed.get("tool") or parsed.get("name") or "unknown_tool")
            except Exception:
                pass
            return input_val
        return "unknown_tool"

    def _tool_signature(self, input_val: Any) -> tuple[str, str]:
        if isinstance(input_val, dict):
            tool = str(input_val.get("tool") or input_val.get("name") or "")
            args = json.dumps(
                input_val.get("args")
                or input_val.get("arguments")
                or input_val.get("parameters")
                or {},
                sort_keys=True,
            )
            return (tool, args)
        if isinstance(input_val, str):
            try:
                parsed = json.loads(input_val)
                if isinstance(parsed, dict):
                    tool = str(parsed.get("tool") or parsed.get("name") or "")
                    args = json.dumps(
                        parsed.get("args")
                        or parsed.get("arguments")
                        or parsed.get("parameters")
                        or {},
                        sort_keys=True,
                    )
                    return (tool, args)
            except Exception:
                pass
            return (input_val, "")
        return ("", "")
