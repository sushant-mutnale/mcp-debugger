"""Live terminal TUI dashboard for monitoring MCP sessions in real-time."""

import asyncio
import json
import sys
from typing import Any

from rich import box
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

from mcp_debugger.attribution.cost import CostCalculator
from mcp_debugger.storage.database import Database


class LiveDashboard:
    """Terminal dashboard monitoring active session trajectory, agent tree, and cost."""

    def __init__(
        self,
        session_id: int,
        db_path: str | None = None,
        console: Console | None = None,
        refresh_rate: float = 1.0,
    ) -> None:
        self.session_id = session_id
        self.db_path = db_path
        self.console = console if console is not None else Console()
        self.refresh_rate = max(0.1, refresh_rate)
        self._running = False
        self._db: Database | None = None

    async def _get_db(self) -> Database:
        """Get or initialize the cached database connection."""
        if self._db is None:
            self._db = Database(db_path=self.db_path)
            await self._db.connect()
        return self._db

    async def close(self) -> None:
        """Close the cached database connection if open."""
        if self._db is not None:
            await self._db.close()
            self._db = None

    def stop(self) -> None:
        """Signal the polling loop to stop."""
        self._running = False

    async def fetch_state(self) -> dict[str, Any]:
        """Fetch session, agents, hierarchy, and steps from database."""
        db = await self._get_db()
        session = await db.get_session(self.session_id)
        if not session:
            return {
                "session": None,
                "agents": [],
                "hierarchy": [],
                "steps": [],
                "total_tokens": 0,
                "total_cost": 0.0,
                "cost_report": None,
            }
        flat_agents = await db.get_agents(self.session_id)
        hierarchy = await db.get_agent_hierarchy(self.session_id)
        steps = await db.get_steps(self.session_id)

        cost_calc = CostCalculator()
        cost_report = cost_calc.compute_session_costs(self.session_id, steps, flat_agents)

        return {
            "session": session,
            "agents": flat_agents,
            "hierarchy": hierarchy,
            "steps": steps,
            "total_tokens": cost_report.total_tokens,
            "total_cost": cost_report.total_cost_usd,
            "cost_report": cost_report,
        }

    def build_header(self, state: dict[str, Any]) -> Panel:
        """Construct header panel showing session id, status, server, transport, steps, tokens, cost."""
        session = state.get("session") or {}
        sid = session.get("id", self.session_id)
        raw_server = session.get("server_name") or session.get("server_command") or "unknown"
        server_str = str(raw_server)[:32] + "..." if len(str(raw_server)) > 35 else str(raw_server)
        server = escape(server_str)
        transport = escape(str(session.get("transport") or "stdio"))
        status = escape(str(session.get("status") or "unknown"))
        status_color = (
            "green"
            if status == "running"
            else ("cyan" if status == "completed" else "yellow")
        )

        steps = state.get("steps", [])
        step_count = len(steps)
        total_tokens = state.get("total_tokens", 0)
        total_cost = state.get("total_cost", 0.0)

        header_text = (
            f"[bold]Session:[/bold] #{sid}  |  "
            f"[bold]Status:[/bold] [{status_color}]{status}[/{status_color}]  |  "
            f"[bold]Server:[/bold] [green]{server}[/green]  |  "
            f"[bold]Transport:[/bold] [yellow]{transport}[/yellow]  |  "
            f"[bold]Steps:[/bold] [cyan]{step_count}[/cyan]  |  "
            f"[bold]Tokens:[/bold] [magenta]{total_tokens:,}[/magenta]  |  "
            f"[bold]Cost:[/bold] [bold green]${total_cost:.4f}[/bold green]"
        )
        return Panel(
            header_text,
            title="[bold green]Live Session Monitor[/bold green]",
            border_style="green",
        )

    def build_agent_tree(self, state: dict[str, Any]) -> Panel:
        """Construct tree panel showing agent hierarchy, roles, and step counts."""
        steps = state.get("steps", [])
        agent_step_counts: dict[Any, int] = {}
        for s in steps:
            aid = s.get("agent_id")
            aname = s.get("agent_name")
            if aid is not None:
                agent_step_counts[aid] = agent_step_counts.get(aid, 0) + 1
            if aname:
                agent_step_counts[aname] = agent_step_counts.get(aname, 0) + 1

        tree = Tree(f"[bold cyan]Agents (Session {self.session_id})[/bold cyan]")
        hierarchy = state.get("hierarchy", [])

        def add_agent_node(parent: Any, agent: dict[str, Any]) -> None:
            aid = agent.get("id")
            aname = escape(str(agent.get("name", "Unknown")))
            role = escape(str(agent["role"])) if agent.get("role") else None
            fw = escape(str(agent["framework"])) if agent.get("framework") else None

            count = 0
            if aid in agent_step_counts:
                count = agent_step_counts[aid]
            elif aname in agent_step_counts:
                count = agent_step_counts[aname]

            role_str = f" [dim]({role})[/dim]" if role else ""
            fw_str = f" [magenta]\\[{fw}][/magenta]" if fw else ""
            label = f"[bold green]{aname}[/bold green]{role_str}{fw_str} [dim cyan]({count} steps)[/dim cyan]"
            sub = parent.add(label)
            for ch in agent.get("children", []):
                add_agent_node(sub, ch)

        if hierarchy:
            for root in hierarchy:
                add_agent_node(tree, root)
        else:
            tree.add("[dim]No agents registered[/dim]")

        return Panel(tree, title="[bold]Agent Hierarchy[/bold]", border_style="cyan")

    def build_event_table(self, state: dict[str, Any]) -> Panel:
        """Construct table panel showing recent 10 trajectory steps."""
        table = Table(box=box.SIMPLE, padding=(0, 1), pad_edge=False, expand=True)
        table.add_column("Step #", justify="right", style="cyan", no_wrap=True)
        table.add_column("Agent", style="green")
        table.add_column("Type", style="yellow")
        table.add_column("Name/Payload", style="white", min_width=12, ratio=2)
        table.add_column("Latency", justify="right", style="magenta")
        table.add_column("Cost", justify="right", style="green")

        steps = state.get("steps", [])
        recent_steps = steps[-10:] if len(steps) > 10 else steps
        cost_report = state.get("cost_report")
        step_cost_map: dict[int, float] = {}
        if cost_report and hasattr(cost_report, "step_costs"):
            for sc in cost_report.step_costs:
                step_cost_map[sc.step_index] = sc.cost_usd

        for s in recent_steps:
            s_idx = s.get("step_index", 0)
            step_str = f"#{s_idx}"
            agent_str = escape(str(s.get("agent_name") or "-"))
            type_str = escape(str(s.get("step_type") or "-"))

            raw_in = s.get("input")
            payload_str = "-"
            if raw_in:
                if isinstance(raw_in, str):
                    try:
                        parsed = json.loads(raw_in)
                    except Exception:
                        parsed = raw_in
                else:
                    parsed = raw_in

                if isinstance(parsed, dict):
                    tool_name = parsed.get("tool") or parsed.get("tool_name") or parsed.get("name")
                    if tool_name:
                        args = parsed.get("arguments") or parsed.get("args") or {}
                        if args:
                            args_str = json.dumps(args)
                            if len(args_str) > 30:
                                args_str = args_str[:27] + "..."
                            payload_str = f"{tool_name}({args_str})"
                        else:
                            payload_str = f"{tool_name}()"
                    elif "thought" in parsed:
                        payload_str = str(parsed["thought"])[:35]
                    elif "task" in parsed:
                        payload_str = f"handoff: {parsed['task']}"[:35]
                    else:
                        payload_str = json.dumps(parsed)[:35]
                else:
                    payload_str = str(parsed)[:35]

            payload_escaped = escape(payload_str)

            lat = s.get("latency_ms")
            lat_str = f"{lat:.1f}ms" if lat is not None else "-"

            if s_idx in step_cost_map:
                c_val = step_cost_map[s_idx]
            else:
                calc = CostCalculator()
                c_val = calc.compute_step_cost(
                    model=calc.extract_model_from_step(s),
                    tokens_input=s.get("tokens_input") or 0,
                    tokens_output=s.get("tokens_output") or 0,
                    step_index=s_idx,
                    agent_id=s.get("agent_id"),
                    agent_name=s.get("agent_name"),
                    step_type=s.get("step_type", "llm_call"),
                ).cost_usd
            cost_str = f"${c_val:.4f}"

            table.add_row(step_str, agent_str, type_str, payload_escaped, lat_str, cost_str)

        if not recent_steps:
            table.add_row("-", "-", "-", "[dim]No steps recorded[/dim]", "-", "-")

        return Panel(table, title="[bold]Recent Trajectory Steps[/bold]", border_style="blue")

    def build_layout(self, state: dict[str, Any]) -> Layout:
        """Split layout into header (size=4) and body (ratio=1) with agent tree and event table."""
        layout = Layout()
        layout.split(
            Layout(name="header", size=4),
            Layout(name="body", ratio=1),
        )
        layout["body"].split_row(
            Layout(name="left", ratio=1),
            Layout(name="right", ratio=2),
        )
        layout["header"].update(self.build_header(state))
        layout["left"].update(self.build_agent_tree(state))
        layout["right"].update(self.build_event_table(state))
        return layout

    async def render_once(self) -> None:
        """Fetch state once and render snapshot to console; exit(1) if session not found."""
        try:
            state = await self.fetch_state()
            if not state.get("session"):
                self.console.print(f"[red]Error: Session {self.session_id} not found.[/red]")
                sys.exit(1)
            layout = self.build_layout(state)
            self.console.print(layout)
        finally:
            await self.close()

    async def run(self) -> None:
        """Start polling loop updating dashboard at refresh_rate seconds."""
        self._running = True
        try:
            state = await self.fetch_state()
            if not state.get("session"):
                self.console.print(f"[red]Error: Session {self.session_id} not found.[/red]")
                sys.exit(1)
            layout = self.build_layout(state)
            refresh_per_sec = max(1, int(1.0 / self.refresh_rate))
            with Live(layout, console=self.console, refresh_per_second=refresh_per_sec) as live:
                while self._running:
                    await asyncio.sleep(self.refresh_rate)
                    if not self._running:
                        break
                    state = await self.fetch_state()
                    if not state.get("session"):
                        break
                    layout["header"].update(self.build_header(state))
                    layout["left"].update(self.build_agent_tree(state))
                    layout["right"].update(self.build_event_table(state))
                    live.refresh()
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        finally:
            self._running = False
            await self.close()
