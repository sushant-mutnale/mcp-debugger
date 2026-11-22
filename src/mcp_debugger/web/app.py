"""FastAPI web application for the MCP Debugger Web UI."""

import json
import math
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from mcp_debugger.attribution.cost import CostCalculator
from mcp_debugger.storage.database import Database

# Global database instance
db: Database | None = None

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application lifespan (startup and shutdown)."""
    global db
    db = Database()
    await db.connect()
    yield
    if db:
        await db.close()


app = FastAPI(
    title="MCP Debugger Web UI",
    description="Web interface for viewing and managing MCP sessions.",
    version="0.1.0",
    lifespan=lifespan,
)

# Allow CORS for localhost only
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://127.0.0.1:8000"],
    allow_credentials=True,
    allow_methods=["GET", "DELETE"],
    allow_headers=["*"],
)

# Mount static files
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def get_db() -> Database:
    """Get the active database connection or raise 500."""
    if db is None:
        raise HTTPException(status_code=500, detail="Database not initialized")
    return db


# ---------------------------------------------------------------------------
# HTML routes
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    """Render the sessions list page."""
    return templates.TemplateResponse(request=request, name="sessions.html")


@app.get("/session/{session_id}", response_class=HTMLResponse)
async def session_detail_page(request: Request, session_id: int) -> HTMLResponse:
    """Render the session detail page."""
    return templates.TemplateResponse(
        request=request,
        name="session_detail.html",
        context={"session_id": session_id},
    )


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------


@app.get("/api/sessions")
async def api_get_sessions(
    page: int = Query(1, ge=1),
    limit: int = Query(25, ge=1, le=200),
    search: str | None = Query(None),
    status: str | None = Query(None),
) -> dict[str, Any]:
    """Return paginated sessions list with optional search/status filter."""
    db_conn = get_db()
    sessions, total = await db_conn.get_sessions_paginated(
        page=page,
        limit=limit,
        search=search or None,
        status_filter=status or None,
    )
    pages = max(1, math.ceil(total / limit))
    return {
        "data": sessions,
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "pages": pages,
        },
    }


@app.get("/api/sessions/stats")
async def api_global_stats() -> dict[str, int]:
    """Return global session counts grouped by status."""
    db_conn = get_db()
    return await db_conn.get_global_session_stats()


@app.get("/api/sessions/{session_id}")
async def api_get_session(session_id: int) -> dict[str, Any]:
    """Return full session metadata, stats, tools, and errors."""
    db_conn = get_db()
    session = await db_conn.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    stats = await db_conn.get_session_stats(session_id)
    tools = await db_conn.get_tools(session_id)
    errors = await db_conn.get_errors(session_id)

    return {
        "session": dict(session),
        "stats": stats,
        "tools": tools,
        "errors": errors,
    }


@app.get("/api/sessions/{session_id}/messages")
async def api_get_messages(
    session_id: int,
    method: str | None = None,
    direction: str | None = None,
    search: str | None = None,
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> list[dict[str, Any]]:
    """Return messages for a specific session with optional filters."""
    db_conn = get_db()
    session = await db_conn.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    messages = await db_conn.get_messages(
        session_id=session_id,
        method=method,
        direction=direction,
        search=search,
        limit=limit,
        offset=offset,
    )
    return messages


@app.get("/api/sessions/{session_id}/agents")
async def api_get_session_agents(session_id: int) -> dict[str, Any]:
    """Return multi-agent hierarchy, handoffs, and performance statistics for a session."""
    db_conn = get_db()
    session = await db_conn.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    agents = await db_conn.get_agents(session_id)
    hierarchy = await db_conn.get_agent_hierarchy(session_id)
    steps = await db_conn.get_steps(session_id)

    agent_id_to_name: dict[int, str] = {
        a["id"]: a["name"] for a in agents if a.get("id") is not None and a.get("name")
    }

    agent_stats: dict[str, dict[str, Any]] = {
        a["name"]: {"steps": 0, "tokens": 0, "cost": 0.0, "latency_sum": 0.0}
        for a in agents
        if a.get("name")
    }

    cost_calculator = CostCalculator()
    handoffs: list[dict[str, Any]] = []

    for s in steps:
        agent_name = s.get("agent_name")
        if not agent_name and s.get("agent_id") in agent_id_to_name:
            agent_name = agent_id_to_name[s["agent_id"]]

        tokens_in = s.get("tokens_input") or 0
        tokens_out = s.get("tokens_output") or 0
        lat = s.get("latency_ms")

        if agent_name:
            if agent_name not in agent_stats:
                agent_stats[agent_name] = {"steps": 0, "tokens": 0, "cost": 0.0, "latency_sum": 0.0}

            agent_stats[agent_name]["steps"] += 1
            agent_stats[agent_name]["tokens"] += tokens_in + tokens_out
            if lat is not None:
                agent_stats[agent_name]["latency_sum"] = round(
                    agent_stats[agent_name]["latency_sum"] + float(lat), 3
                )

            model = cost_calculator.extract_model_from_step(s)
            sc = cost_calculator.compute_step_cost(
                model=model,
                tokens_input=tokens_in,
                tokens_output=tokens_out,
                step_index=s.get("step_index", 0),
                agent_id=s.get("agent_id"),
                agent_name=agent_name,
                step_type=s.get("step_type", "llm_call"),
            )
            agent_stats[agent_name]["cost"] = round(
                agent_stats[agent_name]["cost"] + sc.cost_usd, 6
            )

        if s.get("step_type") == "handoff":
            raw_in = s.get("input") or s.get("input_data")
            in_payload: dict[str, Any] = {}
            if isinstance(raw_in, str):
                try:
                    in_payload = json.loads(raw_in)
                except Exception:
                    in_payload = {}
            elif isinstance(raw_in, dict):
                in_payload = raw_in

            from_agent = in_payload.get("from_agent") or s.get("agent_name") or "unknown"
            to_agent = in_payload.get("to_agent") or "unknown"
            task = in_payload.get("task") or ""
            latency_ms = s.get("latency_ms")
            if latency_ms is None and "latency_ms" in in_payload:
                latency_ms = in_payload.get("latency_ms")

            handoffs.append({
                "step_index": s.get("step_index", 0),
                "from_agent": from_agent,
                "to_agent": to_agent,
                "task": task,
                "latency_ms": latency_ms,
                "created_at": s.get("created_at"),
            })

    return {
        "session_id": session_id,
        "agents": agents,
        "hierarchy": hierarchy,
        "handoffs": handoffs,
        "agent_stats": agent_stats,
    }


@app.delete("/api/sessions/{session_id}", status_code=204)
async def api_delete_session(session_id: int) -> None:
    """Delete a session and all its associated data."""
    db_conn = get_db()
    session = await db_conn.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    await db_conn.delete_session(session_id)
