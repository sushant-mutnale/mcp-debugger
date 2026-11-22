"""End-to-End Multi-Agent Tracing and Attribution Demo.

Demonstrates:
1. Multi-Agent hierarchy creation and role registration
2. Inter-agent handoffs with context state diff tracking
3. Per-step token accounting and cost attribution
4. Causal failure attribution isolating point-of-commitment
5. CI/CD quality gate enforcement and SARIF/JUnit export
"""

from __future__ import annotations

import asyncio

from rich.console import Console

from mcp_debugger.sdk.context import set_current_agent, set_active_session
from mcp_debugger.sdk.handoff import trace_handoff_context
from mcp_debugger.storage.database import Database

console = Console()


async def run_simulation(db_path: str = "demo_multi_agent.db") -> int:
    console.print("\n[bold cyan]🚀 Starting Multi-Agent Debugger Tracing Simulation...[/bold cyan]")

    db = Database(db_path=db_path)
    await db.connect()
    try:
        # 1. Create Debugger Session
        session_id = await db.create_session(
            server_command="python -m agent_fleet",
            friendly_name="Enterprise Multi-Agent Pipeline",
        )
        set_active_session(session_id, db)
        console.print(f"  [green]✓[/green] Created session [bold]#{session_id}[/bold]: '{friendly_name}'" if (friendly_name := "Enterprise Multi-Agent Pipeline") else "")

        # 2. Register Agent Hierarchy
        # Lead Orchestrator
        lead_id = await db.create_agent(
            session_id=session_id,
            name="ChiefArchitect",
            role="Lead Orchestrator",
            framework="crewai",
            metadata={"priority": "high", "model": "gpt-4o"},
        )
        # Subagent 1: Researcher
        researcher_id = await db.create_agent(
            session_id=session_id,
            name="SecurityResearcher",
            role="Vulnerability Scanner",
            framework="crewai",
            parent_agent_id=lead_id,
            metadata={"model": "claude-3-5-sonnet"},
        )
        # Subagent 2: Code Generator
        coder_id = await db.create_agent(
            session_id=session_id,
            name="PatchGenerator",
            role="Automated Coder",
            framework="crewai",
            parent_agent_id=lead_id,
            metadata={"model": "gpt-4o"},
        )
        console.print("  [green]✓[/green] Registered agent hierarchy: [yellow]ChiefArchitect[/yellow] → ([cyan]SecurityResearcher[/cyan], [cyan]PatchGenerator[/cyan])")

        # 3. Simulate Trajectory Steps
        # Step 1: ChiefArchitect Initial Planning
        set_current_agent("ChiefArchitect")
        await db.log_step(
            session_id=session_id,
            step_index=1,
            step_type="thought",
            agent_name="ChiefArchitect",
            agent_id=lead_id,
            input_data='{"plan": "Analyze repo vulnerabilities and apply patch"}',
            output_data='{"task_assigned": "SecurityResearcher"}',
            tokens_input=25_000,
            tokens_output=3_500,
            latency_ms=820.0,
        )

        # Step 2: Handoff from ChiefArchitect -> SecurityResearcher
        state_before = {"phase": "planning", "targets": ["auth.py", "crypto.py"]}
        state_after = {
            "phase": "scanning",
            "targets": ["auth.py", "crypto.py"],
            "scan_mode": "deep_ast",
        }
        async with trace_handoff_context(
            from_agent="ChiefArchitect",
            to_agent="SecurityResearcher",
            task="Scan repository for cryptographic flaws",
            initial_context=state_before,
        ) as h1:
            h1.set_output_context(state_after)

        # Step 3: SecurityResearcher Tool Call
        set_current_agent("SecurityResearcher")
        await db.log_step(
            session_id=session_id,
            step_index=3,
            step_type="tool_call",
            agent_name="SecurityResearcher",
            agent_id=researcher_id,
            input_data='{"tool": "ast_scanner", "file": "auth.py"}',
            output_data='{"findings": ["CVE-2026-X: Weak IV generation on line 42"]}',
            tokens_input=45_000,
            tokens_output=8_000,
            latency_ms=1450.0,
        )

        # Step 4: Handoff from SecurityResearcher -> PatchGenerator
        state_r_before = {"findings": ["CVE-2026-X: Weak IV generation on line 42"]}
        state_r_after = {
            "findings": ["CVE-2026-X: Weak IV generation on line 42"],
            "patch_instruction": "Replace Math.random() with secrets.token_bytes(16)",
        }
        async with trace_handoff_context(
            from_agent="SecurityResearcher",
            to_agent="PatchGenerator",
            task="Generate cryptographic fix",
            initial_context=state_r_before,
        ) as h2:
            h2.set_output_context(state_r_after)

        # Step 5: PatchGenerator LLM Call
        set_current_agent("PatchGenerator")
        await db.log_step(
            session_id=session_id,
            step_index=5,
            step_type="llm_call",
            agent_name="PatchGenerator",
            agent_id=coder_id,
            input_data='{"model": "gpt-4o", "prompt": "Generate diff for auth.py"}',
            output_data='{"diff": "@@ -42 +42 @@\\n-iv = random()\\n+iv = secrets.token_bytes(16)"}',
            tokens_input=60_000,
            tokens_output=15_000,
            latency_ms=2100.0,
        )

        # Step 6: PatchGenerator Tool Execution Error (Simulated Downstream Failure)
        await db.log_step(
            session_id=session_id,
            step_index=6,
            step_type="tool_call",
            agent_name="PatchGenerator",
            agent_id=coder_id,
            input_data='{"tool": "apply_patch", "file": "auth.py", "mode": "strict"}',
            output_data='{"error": "PermissionDenied: Sandbox rejected filesystem write outside /tmp"}',
            tokens_input=10_000,
            tokens_output=1_200,
            latency_ms=450.0,
        )

        console.print("  [green]✓[/green] Logged 6 trajectory steps with token usage, handoffs, and tool execution")
        return session_id
    finally:
        set_active_session(None, None)
        await db.close()


if __name__ == "__main__":
    sid = asyncio.run(run_simulation())
    console.print(f"\n[bold green]Simulation complete! Use session #{sid} for CLI demonstrations.[/bold green]\n")
