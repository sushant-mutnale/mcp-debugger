"""CLI entry point for mcp-debugger."""

import asyncio
from datetime import datetime, timezone
import json
import sqlite3
import sys
from typing import Optional

import aiosqlite
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from mcp_debugger.proxy.stdio_proxy import StdioProxy
from mcp_debugger.storage.database import Database

app = typer.Typer(help="MCP proxy debugger – inspect, record, validate, and replay MCP sessions")
console = Console()


@app.callback()
def callback() -> None:
    """MCP proxy debugger."""


@app.command()
def version() -> None:
    """Show version and exit."""
    try:
        # Check if the terminal encoding supports the emoji
        "✨".encode(console.encoding or "utf-8")
        title = "✨ MCP Debugger"
    except Exception:
        title = "MCP Debugger"

    console.print(
        Panel(
            "mcp-debugger v0.1.0",
            title=title,
            border_style="green",
            safe_box=True,
        )
    )


def convert_utc_to_local_string(utc_str: str) -> str:
    """Convert a UTC time string from SQLite into a local timezone formatted string."""
    utc_str_clean = utc_str.replace("T", " ")
    try:
        dt_utc = datetime.strptime(utc_str_clean, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        dt_local = dt_utc.astimezone()
        return dt_local.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return utc_str


def format_duration(seconds: int, status: str) -> str:
    """Format duration in seconds to a human readable format (e.g. '2m 3s')."""
    if seconds < 0:
        seconds = 0

    if seconds < 60:
        duration_str = f"{seconds}s"
    else:
        minutes = seconds // 60
        secs = seconds % 60
        if minutes < 60:
            duration_str = f"{minutes}m {secs}s"
        else:
            hours = minutes // 60
            mins = minutes % 60
            duration_str = f"{hours}h {mins}m {secs}s"

    if status == "running":
        return f"{duration_str} (running)"
    return duration_str


def truncate_command(cmd: str, max_len: int = 60) -> str:
    """Truncate command string with ellipsis if it exceeds max_len."""
    if len(cmd) <= max_len:
        return cmd
    return cmd[: max_len - 3] + "..."


def get_status_text(status: str) -> Text:
    """Create a formatted Text status with color dot."""
    if status == "completed":
        return Text.assemble(("●", "green"), " completed")
    elif status == "running":
        return Text.assemble(("●", "yellow"), " running")
    else:
        return Text.assemble(("●", "red"), f" {status}")


@app.command(name="proxy")
def proxy(
    server: str = typer.Option(
        ..., "--server", "-s", help="The command to launch the target MCP server"
    ),
    name: Optional[str] = typer.Option(
        None, "--name", "-n", help="A friendly name/label for the debugging session"
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose debug logging"),
) -> None:
    """Launch the transparent stdio proxy and log session traffic to SQLite."""

    async def _run() -> None:
        db = Database()
        await db.connect()

        # Create a new session
        session_id = await db.create_session(server_command=server, friendly_name=name)
        if session_id == -1:
            print("[mcp-debugger error] Failed to create database session.", file=sys.stderr)
            sys.exit(1)

        proxy_engine = StdioProxy(
            server_command=server,
            database=db,
            session_id=session_id,
            verbose=verbose,
        )

        # Run the proxy loop
        exit_code = await proxy_engine.run()
        await db.close()
        sys.exit(exit_code)

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        sys.exit(0)


@app.command(name="list")
def list_sessions(
    limit: int = typer.Option(20, "--limit", "-l", help="Maximum number of sessions to display"),
    status: Optional[str] = typer.Option(
        None,
        "--status",
        help="Filter sessions by status (running, completed, error)",
    ),
    json_mode: bool = typer.Option(
        False,
        "--json",
        help="Output raw JSON array of session objects for scripting",
    ),
) -> None:
    """List historical debugging sessions."""

    async def _run() -> None:
        db = Database()
        try:
            await db.connect()
            sessions = await db.get_sessions(limit=limit, status_filter=status)
        except (sqlite3.DatabaseError, aiosqlite.DatabaseError):
            console.print(
                f"[red]Error: Database file at {db.db_path} appears to be corrupted or invalid.[/red]"
            )
            console.print(
                "[yellow]Recovery Suggestion: Try deleting or renaming the file to reset the database.[/yellow]"
            )
            sys.exit(1)
        except Exception as e:
            console.print(f"[red]Error listing sessions: {e}[/red]")
            sys.exit(1)

        if not sessions:
            if json_mode:
                print("[]")
            else:
                console.print("[yellow]No sessions found. Run mcp-debugger proxy first.[/yellow]")
            await db.close()
            return

        if json_mode:
            json_sessions = []
            for s in sessions:
                json_sessions.append(
                    {
                        "id": s["id"],
                        "name": s["friendly_name"],
                        "server_command": s["server_command"],
                        "started_at": s["started_at"].replace(" ", "T") + "Z"
                        if s["started_at"]
                        else None,
                        "ended_at": s["ended_at"].replace(" ", "T") + "Z"
                        if s["ended_at"]
                        else None,
                        "status": s["status"],
                        "message_count": s["total_messages"],
                        "duration_seconds": s["duration_seconds"],
                    }
                )
            print(json.dumps(json_sessions, indent=2))
        else:
            table = Table(title="MCP Debugger Sessions", border_style="blue")
            table.add_column("ID", justify="right", style="cyan")
            table.add_column("Name", style="magenta")
            table.add_column("Server Command", style="white")
            table.add_column("Started At (Local)", style="white")
            table.add_column("Duration", style="cyan")
            table.add_column("Messages", justify="right", style="green")
            table.add_column("Status", justify="center")

            for s in sessions:
                table.add_row(
                    str(s["id"]),
                    s["friendly_name"] or "—",
                    truncate_command(s["server_command"]),
                    convert_utc_to_local_string(s["started_at"]),
                    format_duration(s["duration_seconds"], s["status"]),
                    str(s["total_messages"]),
                    get_status_text(s["status"]),
                )
            console.print(table)

        await db.close()

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        sys.exit(0)


def main() -> None:
    app()
