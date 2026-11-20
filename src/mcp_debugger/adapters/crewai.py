"""CrewAI multi-agent framework adapter for MCP Debugger."""

from __future__ import annotations

import asyncio
import functools
import json
import time
from typing import Any

from mcp_debugger.sdk.context import (
    get_current_session_id,
    get_tracer_backend,
    next_step_index,
    set_current_agent,
)
from mcp_debugger.sdk.decorators import _dispatch_record_step, _dispatch_record_step_async
from mcp_debugger.sdk.handoff import calculate_context_diff
from mcp_debugger.storage.database import Database

try:
    import crewai  # noqa: F401

    _CREWAI_AVAILABLE = True
except ImportError:
    _CREWAI_AVAILABLE = False


class CrewAITracker:
    """Tracks CrewAI agents, task delegations, and tool invocations."""

    def __init__(
        self,
        session_id: int | None = None,
        db: Database | None = None,
    ) -> None:
        self.session_id = session_id or get_current_session_id() or 0
        self.db = db
        self._agent_name_to_id: dict[str, int] = {}
        self._current_agent_name: str | None = None
        self._agent_counter = 0

    def register_agent(
        self,
        name: str,
        role: str | None = None,
        parent_agent_name: str | None = None,
        framework: str = "crewai",
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """Register a CrewAI agent in the database agents table."""
        self._agent_counter += 1
        assigned_id = self._agent_counter
        parent_id = (
            self._agent_name_to_id.get(parent_agent_name)
            if parent_agent_name
            else None
        )
        self._agent_name_to_id[name] = assigned_id

        db_instance = self.db
        if db_instance is None:
            backend = get_tracer_backend()
            if backend and hasattr(backend, "db"):
                db_instance = backend.db

        if db_instance and self.session_id:

            async def _create() -> int:
                await db_instance.connect()
                return await db_instance.create_agent(
                    session_id=self.session_id,
                    name=name,
                    role=role,
                    parent_agent_id=parent_id,
                    framework=framework,
                    metadata=metadata,
                )

            try:
                loop = asyncio.get_running_loop()
                task = loop.create_task(_create())
                backend = get_tracer_backend()
                if backend and hasattr(backend, "_pending_tasks"):
                    backend._pending_tasks.add(task)
                    task.add_done_callback(backend._pending_tasks.discard)
            except RuntimeError:
                asyncio.run(_create())

        return assigned_id

    async def register_agent_async(
        self,
        name: str,
        role: str | None = None,
        parent_agent_name: str | None = None,
        framework: str = "crewai",
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """Async variant of agent registration."""
        self._agent_counter += 1
        assigned_id = self._agent_counter
        parent_id = (
            self._agent_name_to_id.get(parent_agent_name)
            if parent_agent_name
            else None
        )
        self._agent_name_to_id[name] = assigned_id

        db_instance = self.db
        if db_instance is None:
            backend = get_tracer_backend()
            if backend and hasattr(backend, "db"):
                db_instance = backend.db

        if db_instance and self.session_id:
            await db_instance.connect()
            await db_instance.create_agent(
                session_id=self.session_id,
                name=name,
                role=role,
                parent_agent_id=parent_id,
                framework=framework,
                metadata=metadata,
            )

        return assigned_id

    def on_task_handoff(
        self,
        from_agent: str,
        to_agent: str,
        task: str | None = None,
        context: Any = None,
        output: Any = None,
        latency_ms: float = 0.0,
    ) -> None:
        """Record an inter-agent task delegation handoff step."""
        diff = calculate_context_diff(context or {}, output or {})
        input_payload = {
            "from_agent": from_agent,
            "to_agent": to_agent,
            "task": task,
            "transferred_context": context,
        }
        output_payload = {
            "to_agent": to_agent,
            "output": output,
            "context_diff": diff,
        }
        _dispatch_record_step(
            session_id=self.session_id,
            step_index=next_step_index(),
            step_type="handoff",
            agent_name=from_agent,
            input_data=json.dumps(input_payload, default=str),
            output_data=json.dumps(output_payload, default=str),
            latency_ms=latency_ms,
        )
        self._current_agent_name = to_agent
        set_current_agent(to_agent)

    def on_tool_call(
        self,
        agent_name: str,
        tool_name: str,
        tool_input: Any,
        tool_output: Any,
        latency_ms: float | None = None,
    ) -> None:
        """Record an agent tool execution step."""
        input_payload = {"tool": tool_name, "args": tool_input}
        _dispatch_record_step(
            session_id=self.session_id,
            step_index=next_step_index(),
            step_type="tool_call",
            agent_name=agent_name,
            input_data=json.dumps(input_payload, default=str),
            output_data=str(tool_output),
            latency_ms=latency_ms,
        )

    def on_agent_thought(
        self,
        agent_name: str,
        thought: str,
        input_prompt: str = "Reasoning step",
    ) -> None:
        """Record an agent thought reasoning step."""
        _dispatch_record_step(
            session_id=self.session_id,
            step_index=next_step_index(),
            step_type="thought",
            agent_name=agent_name,
            input_data=input_prompt,
            output_data=thought,
            latency_ms=0.0,
        )


def trace_crewai(crew: Any) -> Any:
    """Wrap a CrewAI Crew instance to track execution, agent hierarchy, and tasks."""
    tracker = CrewAITracker()

    manager = getattr(crew, "manager_agent", None)
    if manager:
        mgr_role = getattr(manager, "role", "Manager")
        tracker.register_agent(
            name=mgr_role,
            role=mgr_role,
            metadata={"goal": getattr(manager, "goal", "")},
        )

    for agent in getattr(crew, "agents", []):
        role = getattr(agent, "role", "Agent")
        tracker.register_agent(
            name=role,
            role=role,
            parent_agent_name=getattr(manager, "role", None) if manager else None,
            metadata={"goal": getattr(agent, "goal", "")},
        )

    original_kickoff = crew.kickoff
    original_kickoff_async = getattr(crew, "kickoff_async", None)

    @functools.wraps(original_kickoff)
    def wrapped_kickoff(inputs: dict[str, Any] | None = None) -> Any:
        start_time = time.perf_counter()
        primary_agent = (
            getattr(manager, "role", None)
            if manager
            else getattr(crew.agents[0], "role", "crew_agent")
            if getattr(crew, "agents", None)
            else "crew_agent"
        )
        tracker.on_agent_thought(
            agent_name=primary_agent,
            thought=f"Initiating crew execution with inputs: {inputs}",
        )
        res = original_kickoff(inputs)
        latency = (time.perf_counter() - start_time) * 1000.0
        _dispatch_record_step(
            session_id=tracker.session_id,
            step_index=next_step_index(),
            step_type="thought",
            agent_name=primary_agent,
            input_data=json.dumps(inputs or {}, default=str),
            output_data=json.dumps(res, default=str),
            latency_ms=latency,
        )
        return res

    crew.kickoff = wrapped_kickoff

    if original_kickoff_async:

        @functools.wraps(original_kickoff_async)
        async def wrapped_kickoff_async(inputs: dict[str, Any] | None = None) -> Any:
            start_time = time.perf_counter()
            primary_agent = (
                getattr(manager, "role", None)
                if manager
                else getattr(crew.agents[0], "role", "crew_agent")
                if getattr(crew, "agents", None)
                else "crew_agent"
            )
            tracker.on_agent_thought(
                agent_name=primary_agent,
                thought=f"Initiating async crew execution with inputs: {inputs}",
            )
            res = await original_kickoff_async(inputs)
            latency = (time.perf_counter() - start_time) * 1000.0
            await _dispatch_record_step_async(
                session_id=tracker.session_id,
                step_index=next_step_index(),
                step_type="thought",
                agent_name=primary_agent,
                input_data=json.dumps(inputs or {}, default=str),
                output_data=json.dumps(res, default=str),
                latency_ms=latency,
            )
            return res

        crew.kickoff_async = wrapped_kickoff_async

    return crew
