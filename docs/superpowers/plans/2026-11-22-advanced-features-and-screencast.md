# Advanced Features & Authentic Screencast Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a real-time terminal TUI dashboard (`mcp-debugger live`), an interactive Web UI Multi-Agent Flow graph, and an automated real-browser screencast pipeline producing an authentic, fast-paced demo recording to replace the synthetic PIL GIF.

**Architecture:** 
1. **Live TUI (`src/mcp_debugger/live/`)**: Built with `rich.live.Live`, `rich.layout.Layout`, and `rich.tree.Tree`, polling SQLite session events to render a multi-pane real-time terminal dashboard with agent hierarchy and streaming step tables.
2. **Web UI Multi-Agent Topology (`src/mcp_debugger/web/`)**: Add a `/api/sessions/{session_id}/agents` endpoint in FastAPI and an interactive Agent Flow visualizer in `session_detail.html` / `session.js` showing clickable agent cards, handoff arrows with context diffs, and agent timeline filtering.
3. **Authentic Screencast Pipeline (`scripts/record_screencast.py`)**: Automate real execution of `examples/demo_multi_agent_tracing.py`, launch the real Web UI, drive Chrome via DevTools MCP / CDP, capture actual viewport frames to MP4, transcode to high-FPS `docs/demo.gif` using `imageio-ffmpeg`, and update `README.md`.

**Tech Stack:** Python 3.11+, Rich, FastAPI, Jinja2, Chrome DevTools MCP / CDP, imageio-ffmpeg, pytest, ruff.

---

### Task 1: Live Terminal TUI Dashboard (`mcp-debugger live`)

**Files:**
- Create: `src/mcp_debugger/live/dashboard.py`
- Create: `src/mcp_debugger/live/__init__.py`
- Modify: `src/mcp_debugger/cli.py`
- Test: `tests/test_cli/test_live.py`

- [ ] **Step 1: Write the failing test for `mcp-debugger live`**

Create `tests/test_cli/test_live.py`:
```python
"""Tests for mcp-debugger live TUI command."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from mcp_debugger.cli import app
from mcp_debugger.storage.database import Database

runner = CliRunner()


@pytest.fixture
def sample_session_db(tmp_path):
    db_file = tmp_path / "test_live.db"

    async def _populate():
        db = Database(db_path=str(db_file))
        await db.connect()
        sess_id = await db.create_session("stdio", "server.py")
        await db.register_agent(
            session_id=sess_id,
            agent_name="Coordinator",
            role="lead",
            model="claude-3-opus",
        )
        await db.register_agent(
            session_id=sess_id,
            agent_name="Researcher",
            parent_agent_name="Coordinator",
            role="worker",
            model="claude-3-haiku",
        )
        await db.log_step(
            session_id=sess_id,
            step_type="tool_call",
            agent_name="Coordinator",
            name="search_db",
            latency_ms=120.0,
            cost_usd=0.002,
            tokens_in=150,
            tokens_out=60,
        )
        await db.close()
        return db_file, sess_id

    import asyncio

    return asyncio.run(_populate())


def test_live_once_flag(sample_session_db, monkeypatch):
    db_file, sess_id = sample_session_db
    monkeypatch.setenv("MCP_DEBUGGER_DATABASE_PATH", str(db_file))

    result = runner.invoke(app, ["live", str(sess_id), "--once"])
    assert result.exit_code == 0
    assert "Live Session Monitor" in result.output
    assert "Coordinator" in result.output
    assert "search_db" in result.output


def test_live_nonexistent_session(tmp_path, monkeypatch):
    db_file = tmp_path / "empty.db"
    monkeypatch.setenv("MCP_DEBUGGER_DATABASE_PATH", str(db_file))

    result = runner.invoke(app, ["live", "999", "--once"])
    assert result.exit_code != 0
    assert "not found" in result.output.lower() or "error" in result.output.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/test_cli/test_live.py -v`
Expected: FAIL with `No such command 'live'`

- [ ] **Step 3: Implement `src/mcp_debugger/live/dashboard.py`**

Create `src/mcp_debugger/live/__init__.py`:
```python
"""Live dashboard module."""

from mcp_debugger.live.dashboard import LiveDashboard

__all__ = ["LiveDashboard"]
```

Create `src/mcp_debugger/live/dashboard.py`:
```python
"""Real-time Terminal UI Dashboard for live session monitoring."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any

from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from mcp_debugger.storage.database import Database


class LiveDashboard:
    """Renders a real-time multi-pane Rich dashboard for session activity."""

    def __init__(
        self,
        session_id: int,
        db_path: str | None = None,
        console: Console | None = None,
        refresh_rate: float = 1.0,
    ) -> None:
        self.session_id = session_id
        self.db_path = db_path or os.getenv("MCP_DEBUGGER_DATABASE_PATH", "mcp_debugger.db")
        self.console = console or Console()
        self.refresh_rate = refresh_rate

    async def fetch_state(self) -> dict[str, Any]:
        """Fetch session, agent hierarchy, steps, and cost summaries."""
        db = Database(db_path=self.db_path)
        await db.connect()
        try:
            session = await db.get_session(self.session_id)
            if not session:
                return {}
            agents = await db.get_agents(self.session_id)
            hierarchy = await db.get_agent_hierarchy(self.session_id)
            steps = await db.get_steps(self.session_id)
            return {
                "session": session,
                "agents": agents,
                "hierarchy": hierarchy,
                "steps": steps,
            }
        finally:
            await db.close()

    def build_header(self, state: dict[str, Any]) -> Panel:
        sess = state.get("session", {})
        steps = state.get("steps", [])
        total_tokens = sum(s.get("total_tokens") or ((s.get("tokens_in") or 0) + (s.get("tokens_out") or 0)) for s in steps)
        total_cost = sum(s.get("cost_usd") or 0.0 for s in steps)

        title = f"[bold white]MCP Debugger[/bold white] [bold cyan]Live Monitor[/bold cyan] — Session [bold yellow]#{self.session_id}[/bold yellow]"
        status_line = (
            f"[bold]Transport:[/bold] {sess.get('transport_type', 'stdio')} | "
            f"[bold]Server:[/bold] {sess.get('server_command', 'n/a')} | "
            f"[bold]Steps:[/bold] [green]{len(steps)}[/green] | "
            f"[bold]Tokens:[/bold] [cyan]{total_tokens:,}[/cyan] | "
            f"[bold]Est. Cost:[/bold] [yellow]${total_cost:.4f}[/yellow]"
        )
        return Panel(status_line, title=title, border_style="cyan", padding=(0, 1))

    def build_agent_tree(self, state: dict[str, Any]) -> Panel:
        hierarchy = state.get("hierarchy", [])
        steps = state.get("steps", [])
        step_counts: dict[str, int] = {}
        for s in steps:
            name = s.get("agent_name") or "Main"
            step_counts[name] = step_counts.get(name, 0) + 1

        tree = Tree(f"[bold green]Agent Execution Fleet[/bold green] ({len(state.get('agents', []))} agents)")

        def _add_nodes(parent_node: Tree, nodes: list[dict[str, Any]]) -> None:
            for node in nodes:
                name = node.get("agent_name", "Unknown")
                role = node.get("role", "")
                count = step_counts.get(name, 0)
                label = f"[bold cyan]{name}[/bold cyan] [dim]({role})[/dim] - [yellow]{count} steps[/yellow]"
                child_branch = parent_node.add(label)
                children = node.get("children", [])
                if children:
                    _add_nodes(child_branch, children)

        if hierarchy:
            _add_nodes(tree, hierarchy)
        else:
            tree.add("[dim italic]No registered multi-agent hierarchy[/dim italic]")

        return Panel(tree, title="[bold]Agent Topology[/bold]", border_style="blue")

    def build_event_table(self, state: dict[str, Any]) -> Panel:
        steps = state.get("steps", [])
        recent_steps = steps[-10:] if steps else []

        table = Table(expand=True, box=None)
        table.add_column("#", justify="right", style="dim", width=4)
        table.add_column("Agent", style="cyan", width=14)
        table.add_column("Type", style="magenta", width=12)
        table.add_column("Name / Payload", style="white")
        table.add_column("Latency", justify="right", style="green", width=9)
        table.add_column("Cost", justify="right", style="yellow", width=8)

        for s in recent_steps:
            idx = str(s.get("step_index", 0))
            agent = s.get("agent_name") or "Main"
            stype = s.get("step_type", "step")
            name = s.get("name") or s.get("tool_name") or "-"
            lat = f"{s.get('latency_ms', 0):.0f}ms" if s.get("latency_ms") is not None else "-"
            cost = f"${s.get('cost_usd', 0):.4f}" if s.get("cost_usd") is not None else "-"
            table.add_row(idx, agent, stype, name, lat, cost)

        if not recent_steps:
            table.add_row("-", "-", "No steps logged yet", "-", "-", "-")

        return Panel(table, title="[bold]Live Event Stream (Recent 10)[/bold]", border_style="green")

    def build_layout(self, state: dict[str, Any]) -> Layout:
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
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
        state = await self.fetch_state()
        if not state:
            self.console.print(f"[red]Error: Session {self.session_id} not found in {self.db_path}[/red]")
            sys.exit(1)
        self.console.print(self.build_layout(state))

    async def run(self) -> None:
        state = await self.fetch_state()
        if not state:
            self.console.print(f"[red]Error: Session {self.session_id} not found in {self.db_path}[/red]")
            sys.exit(1)

        layout = self.build_layout(state)
        with Live(layout, console=self.console, refresh_per_second=int(1.0 / self.refresh_rate)) as live:
            while True:
                await asyncio.sleep(self.refresh_rate)
                state = await self.fetch_state()
                if state:
                    live.update(self.build_layout(state))
```

- [ ] **Step 4: Register `live` command in `src/mcp_debugger/cli.py`**

In `src/mcp_debugger/cli.py`, add the `live` Typer command:
```python
@app.command(name="live")
def live_command(
    session_id: int | None = typer.Argument(
        None, help="The ID of the session to monitor (defaults to latest active session)"
    ),
    refresh: float = typer.Option(
        1.0, "--refresh", "-r", help="Refresh rate in seconds (default: 1.0s)"
    ),
    once: bool = typer.Option(
        False, "--once", help="Render single snapshot and exit immediately"
    ),
) -> None:
    """Real-time terminal dashboard monitoring active session execution and agent trees."""
    from mcp_debugger.live.dashboard import LiveDashboard

    async def _resolve_latest_session_id() -> int | None:
        db = Database()
        await db.connect()
        try:
            sessions = await db.list_sessions(limit=1)
            return sessions[0]["id"] if sessions else None
        finally:
            await db.close()

    async def _run() -> None:
        target_id = session_id
        if target_id is None:
            target_id = await _resolve_latest_session_id()
            if target_id is None:
                console.print("[red]No sessions found in database to monitor.[/red]")
                sys.exit(1)

        dashboard = LiveDashboard(session_id=target_id, console=console, refresh_rate=refresh)
        if once:
            await dashboard.render_once()
        else:
            try:
                await dashboard.run()
            except KeyboardInterrupt:
                console.print("\n[dim]Live monitor exited.[/dim]")

    asyncio.run(_run())
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run --extra dev pytest tests/test_cli/test_live.py -v`
Expected: PASS

- [ ] **Step 6: Commit changes**

Check `.agent/config.yml` for `auto_commit` setting.
If `auto_commit: true`:
```bash
git add src/mcp_debugger/live/ tests/test_cli/test_live.py src/mcp_debugger/cli.py
git commit -m "feat(live): add real-time terminal TUI dashboard command"
```

---

### Task 2: Interactive Web UI Multi-Agent Flow & Topology

**Files:**
- Modify: `src/mcp_debugger/web/app.py`
- Modify: `src/mcp_debugger/web/templates/session_detail.html`
- Modify: `src/mcp_debugger/web/static/session.js`
- Test: `tests/test_web/test_topology_api.py`

- [ ] **Step 1: Write failing test for `/api/sessions/{session_id}/agents` endpoint**

Create `tests/test_web/test_topology_api.py`:
```python
"""Tests for Web UI agent topology API endpoint."""

import pytest
from fastapi.testclient import TestClient

from mcp_debugger.storage.database import Database
from mcp_debugger.web.app import app


@pytest.fixture
def client_with_agents(tmp_path, monkeypatch):
    db_file = tmp_path / "web_agents.db"
    monkeypatch.setenv("MCP_DEBUGGER_DATABASE_PATH", str(db_file))

    import asyncio

    async def _setup():
        db = Database(db_path=str(db_file))
        await db.connect()
        sess_id = await db.create_session("stdio", "agent_runner.py")
        await db.register_agent(
            session_id=sess_id,
            agent_name="Coordinator",
            role="planner",
            model="claude-3-opus",
        )
        await db.register_agent(
            session_id=sess_id,
            agent_name="CodeReviewer",
            parent_agent_name="Coordinator",
            role="reviewer",
            model="gpt-4o",
        )
        await db.log_step(
            session_id=sess_id,
            step_type="handoff",
            agent_name="Coordinator",
            input_data='{"from_agent": "Coordinator", "to_agent": "CodeReviewer", "task": "Review PR"}',
            latency_ms=45.0,
        )
        await db.close()
        return sess_id

    sess_id = asyncio.run(_setup())
    with TestClient(app) as client:
        yield client, sess_id


def test_get_session_agents_topology(client_with_agents):
    client, sess_id = client_with_agents
    resp = client.get(f"/api/sessions/{sess_id}/agents")
    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"] == sess_id
    assert len(data["agents"]) == 2
    assert len(data["hierarchy"]) == 1
    assert data["hierarchy"][0]["agent_name"] == "Coordinator"
    assert data["hierarchy"][0]["children"][0]["agent_name"] == "CodeReviewer"
    assert len(data["handoffs"]) == 1
    assert data["handoffs"][0]["from_agent"] == "Coordinator"
    assert data["handoffs"][0]["to_agent"] == "CodeReviewer"


def test_get_session_agents_404(client_with_agents):
    client, _ = client_with_agents
    resp = client.get("/api/sessions/99999/agents")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/test_web/test_topology_api.py -v`
Expected: FAIL with `404 Not Found` for `/api/sessions/{sess_id}/agents`

- [ ] **Step 3: Implement endpoint in `src/mcp_debugger/web/app.py`**

Add endpoint in `src/mcp_debugger/web/app.py`:
```python
@app.get("/api/sessions/{session_id}/agents")
async def get_session_agents(session_id: int) -> dict[str, Any]:
    """Return multi-agent hierarchy, registered agents, and handoff events."""
    database = get_db()
    session = await database.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    agents = await database.get_agents(session_id)
    hierarchy = await database.get_agent_hierarchy(session_id)
    steps = await database.get_steps(session_id)

    handoffs = []
    agent_stats: dict[str, dict[str, Any]] = {}
    for a in agents:
        name = a["agent_name"]
        agent_stats[name] = {"steps": 0, "tokens": 0, "cost": 0.0, "latency_sum": 0.0}

    for s in steps:
        agent_name = s.get("agent_name") or "Main"
        if agent_name not in agent_stats:
            agent_stats[agent_name] = {"steps": 0, "tokens": 0, "cost": 0.0, "latency_sum": 0.0}
        agent_stats[agent_name]["steps"] += 1
        agent_stats[agent_name]["tokens"] += (s.get("tokens_in") or 0) + (s.get("tokens_out") or 0)
        agent_stats[agent_name]["cost"] += s.get("cost_usd") or 0.0
        if s.get("latency_ms"):
            agent_stats[agent_name]["latency_sum"] += s.get("latency_ms")

        if s.get("step_type") == "handoff":
            raw_in = s.get("input") or s.get("input_data")
            in_payload = {}
            if isinstance(raw_in, str):
                try:
                    import json
                    in_payload = json.loads(raw_in)
                except Exception:
                    pass
            elif isinstance(raw_in, dict):
                in_payload = raw_in

            handoffs.append({
                "step_index": s.get("step_index", 0),
                "from_agent": in_payload.get("from_agent") or agent_name,
                "to_agent": in_payload.get("to_agent") or "unknown",
                "task": in_payload.get("task") or "",
                "latency_ms": s.get("latency_ms"),
                "created_at": s.get("created_at"),
            })

    return {
        "session_id": session_id,
        "agents": agents,
        "hierarchy": hierarchy,
        "handoffs": handoffs,
        "agent_stats": agent_stats,
    }
```

- [ ] **Step 4: Update Web UI templates & JavaScript for interactive topology**

In `src/mcp_debugger/web/templates/session_detail.html`:
Add the tab button:
```html
<button class="tab-btn" data-tab="agents">🤖 Multi-Agent Flow</button>
```
And add tab panel:
```html
<!-- Tab: Multi-Agent Flow -->
<div id="tab-agents" class="tab-panel hidden">
    <div class="mb-6 flex items-center justify-between">
        <div>
            <h3 class="text-lg font-semibold text-white">Agent Execution Topology</h3>
            <p class="text-xs text-gray-400">Interactive visual flow of autonomous agents, delegations, and handoffs.</p>
        </div>
        <div id="agentsFleetSummary" class="text-xs text-gray-400 font-mono"></div>
    </div>
    <div id="agentCanvas" class="bg-[#1a1b26] border border-[#2f354a] rounded-xl p-6 min-h-[280px] mb-6 flex flex-wrap gap-6 items-center justify-start">
        <p class="text-gray-500 text-sm">Loading multi-agent topology…</p>
    </div>
    <div id="handoffListContainer">
        <h4 class="text-sm font-semibold text-gray-300 mb-3 uppercase tracking-wider">Inter-Agent Handoffs</h4>
        <div id="handoffList" class="flex flex-col gap-2">
            <p class="text-gray-500 text-xs">No handoffs detected in this session.</p>
        </div>
    </div>
</div>
```

In `src/mcp_debugger/web/static/session.js`:
Add loading & interactive rendering for `/api/sessions/{session_id}/agents`:
- Render cards for each agent with model badges, token metrics, step count, and click-to-filter handlers.
- Render SVG transition arrows or handoff cards between cooperating agents.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run --extra dev pytest tests/test_web/test_topology_api.py -v`
Expected: PASS

- [ ] **Step 6: Commit changes**

Check `.agent/config.yml` for `auto_commit` setting.
If `auto_commit: true`:
```bash
git add src/mcp_debugger/web/ tests/test_web/test_topology_api.py
git commit -m "feat(web): add interactive multi-agent topology tab and api endpoint"
```

---

### Task 3: Automated Real Screencast Pipeline (`scripts/record_screencast.py`)

**Files:**
- Create: `scripts/record_screencast.py`
- Test: execute script to produce `docs/demo.mp4` and `docs/demo.gif`

- [ ] **Step 1: Write `scripts/record_screencast.py`**

Write `scripts/record_screencast.py` to:
1. Seed a realistic multi-agent trace session using `examples/demo_multi_agent_tracing.py` into `data/screencast_demo.db`.
2. Start the FastAPI Web UI on `http://127.0.0.1:8080` in a subprocess.
3. Use Chrome DevTools MCP or automated CDP browser actions to:
   - Resize viewport to 1280x720.
   - Start screencast recording (`screencast_start`).
   - Navigate through Session Overview (`/`).
   - Click into the Multi-Agent Tracing Session.
   - Click the "Multi-Agent Flow" tab: show the interactive Agent Topology & cards.
   - Click on the "Tools" tab & inspect latency.
   - Stop screencast recording (`screencast_stop`).
4. Read the resulting MP4 frames using `imageio.v3` / `imageio-ffmpeg` and generate an animated GIF `docs/demo.gif` (optimized with 15-20 fps, 800px width for fast loading).
5. Copy the source MP4 to `docs/demo.mp4` for full HD viewing.

```python
"""Automated real screencast recording pipeline for mcp-debugger."""

import asyncio
import os
import shutil
import subprocess
import time
from pathlib import Path

# Implements headless or DevTools capture -> docs/demo.mp4 & docs/demo.gif
```

- [ ] **Step 2: Run `scripts/record_screencast.py` and verify output**

Run: `uv run --with imageio --with imageio-ffmpeg python scripts/record_screencast.py`
Expected:
- Real Web UI started and captured.
- `docs/demo.mp4` generated.
- `docs/demo.gif` generated from real frames (not fake PIL).
- Verify file existence and non-zero size.

- [ ] **Step 3: Update `README.md` and documentation**

Update `README.md` to feature the real demo screencast and document `mcp-debugger live`.

- [ ] **Step 4: Commit changes**

Check `.agent/config.yml` for `auto_commit` setting.
If `auto_commit: true`:
```bash
git add scripts/record_screencast.py docs/demo.gif docs/demo.mp4 README.md docs/commands.md
git commit -m "feat(media): replace synthetic GIF with authentic real screencast demo"
```

---

### Task 4: Complete Suite Verification & Quality Gate

**Files:**
- None (verification across entire workspace)

- [ ] **Step 1: Run full test suite with coverage**

Run: `uv run --extra dev pytest -q`
Expected: All tests pass (372+ passing, 0 failing, >= 89% coverage).

- [ ] **Step 2: Run linter and formatting check**

Run: `uv run ruff check .`
Expected: 0 errors.

- [ ] **Step 3: Check git status and cleanliness**

Run: `git status`
Expected: Clean working tree.
