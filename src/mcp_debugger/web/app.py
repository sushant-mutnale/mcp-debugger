from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from mcp_debugger.storage.database import Database

# Global database instance
db: Database | None = None


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

# Allow CORS for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust in production if necessary
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Setup templates
BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def get_db() -> Database:
    """Get the active database connection."""
    if db is None:
        raise HTTPException(status_code=500, detail="Database not initialized")
    return db


@app.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    """Render the home page with the sessions list."""
    # We fetch sessions client-side via the API to make the UI more responsive,
    # but we could also inject initial data here if desired.
    return templates.TemplateResponse(request=request, name="sessions.html")


@app.get("/api/sessions")
async def api_get_sessions(
    limit: int = Query(25, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    status: str | None = None,
) -> list[dict[str, Any]]:
    """Get a list of sessions."""
    db_conn = get_db()
    sessions = await db_conn.get_sessions(limit=limit, offset=offset, status_filter=status)
    return sessions


@app.get("/api/sessions/{session_id}")
async def api_get_session(session_id: int) -> dict[str, Any]:
    """Get detailed information about a specific session."""
    db_conn = get_db()
    session = await db_conn.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    tools = await db_conn.get_tools(session_id)
    errors = await db_conn.get_errors(session_id)

    return {
        **session,
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
    """Get messages for a specific session."""
    db_conn = get_db()

    # Verify session exists
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
