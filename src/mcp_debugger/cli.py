"""CLI entry point for mcp-debugger."""

import asyncio
from datetime import datetime, timezone
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Optional

import aiosqlite
import typer
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
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


@app.command(name="inspect")
def inspect(
    session_id: int = typer.Argument(..., help="The ID of the session to inspect"),
    method: Optional[str] = typer.Option(
        None,
        "--method",
        help="Filter messages by method name (case-sensitive)",
    ),
    direction: Optional[str] = typer.Option(
        None,
        "--direction",
        help="Filter messages by direction (client_to_server, server_to_client)",
    ),
    search: Optional[str] = typer.Option(
        None,
        "--search",
        help="Substring search in the JSON body (raw text)",
    ),
    limit: Optional[int] = typer.Option(
        None,
        "--limit",
        help="Maximum number of messages to show",
    ),
    offset: Optional[int] = typer.Option(
        None,
        "--offset",
        help="Skip the first N messages",
    ),
    json_mode: bool = typer.Option(
        False,
        "--json",
        help="Output raw JSON instead of Rich terminal format",
    ),
    output: Optional[str] = typer.Option(
        None,
        "--output",
        "-o",
        help="Write output to a file instead of stdout",
    ),
) -> None:
    """Inspect and format captured messages from a specific session."""

    def rebuild_jsonrpc(row: dict[str, Any]) -> dict[str, Any]:
        msg: dict[str, Any] = {"jsonrpc": "2.0"}
        if row.get("message_id") is not None:
            raw_id = row["message_id"]
            try:
                msg["id"] = int(raw_id)
            except ValueError:
                msg["id"] = raw_id

        if row.get("method") is not None and row.get("message_type") in ("request", "notification"):
            msg["method"] = row["method"]

        for field in ("params", "result", "error"):
            val = row.get(field)
            if val is not None:
                try:
                    msg[field] = json.loads(val)
                except Exception:
                    msg[field] = val
        return msg

    async def _run() -> None:
        db = Database()
        try:
            await db.connect()
            session = await db.get_session(session_id)
        except (sqlite3.DatabaseError, aiosqlite.DatabaseError):
            console.print(
                f"[red]Error: Database file at {db.db_path} appears to be corrupted or invalid.[/red]"
            )
            console.print(
                "[yellow]Recovery Suggestion: Try deleting or renaming the file to reset the database.[/yellow]"
            )
            sys.exit(1)
        except Exception as e:
            console.print(f"[red]Error connecting to database: {e}[/red]")
            sys.exit(1)

        if not session:
            console.print(f"Session {session_id} not found")
            await db.close()
            sys.exit(1)

        try:
            messages = await db.get_messages(
                session_id=session_id,
                method=method,
                direction=direction,
                search=search,
                limit=limit,
                offset=offset,
            )
        except Exception as e:
            console.print(f"[red]Error fetching messages: {e}[/red]")
            await db.close()
            sys.exit(1)

        if not messages:
            if json_mode:
                output_str = "[]"
                if output:
                    with open(output, "w", encoding="utf-8") as f:
                        f.write(output_str + "\n")
                else:
                    print(output_str)
            else:
                if output:
                    with open(output, "w", encoding="utf-8") as f:
                        f.write("No messages\n")
                else:
                    console.print("No messages")
            await db.close()
            return

        if json_mode:
            json_messages = []
            for msg in messages:
                params_val = None
                if msg.get("params") is not None:
                    try:
                        params_val = json.loads(msg["params"])
                    except Exception:
                        params_val = msg["params"]

                result_val = None
                if msg.get("result") is not None:
                    try:
                        result_val = json.loads(msg["result"])
                    except Exception:
                        result_val = msg["result"]

                error_val = None
                if msg.get("error") is not None:
                    try:
                        error_val = json.loads(msg["error"])
                    except Exception:
                        error_val = msg["error"]

                timestamp_sec = msg["timestamp"] / 1000.0 if msg.get("timestamp") else None

                json_messages.append(
                    {
                        "id": msg["id"],
                        "direction": msg["direction"],
                        "method": msg["method"],
                        "timestamp": timestamp_sec,
                        "latency_ms": msg["latency_ms"],
                        "params": params_val,
                        "result": result_val,
                        "error": error_val,
                    }
                )
            output_str = json.dumps(json_messages, indent=2)
            if output:
                with open(output, "w", encoding="utf-8") as f:
                    f.write(output_str + "\n")
            else:
                print(output_str)
        else:
            panels = []
            for msg in messages:
                envelope = rebuild_jsonrpc(msg)
                json_body = json.dumps(envelope, indent=2)
                syntax_body = Syntax(json_body, "json")

                time_str = "unknown"
                if msg.get("timestamp") is not None:
                    try:
                        dt = datetime.fromtimestamp(msg["timestamp"] / 1000.0)
                        time_str = dt.strftime("%H:%M:%S.%f")[:-3]
                    except Exception:
                        time_str = str(msg["timestamp"])

                direction_str = msg.get("direction")
                is_error = msg.get("error") is not None

                header = Text()
                if direction_str == "client_to_server":
                    header.append("➜ ", style="blue bold")
                    header.append("client → server", style="blue")
                    border_style = "blue"
                else:
                    if is_error:
                        header.append("◀ ", style="red bold")
                        header.append("server → client", style="red")
                        border_style = "red"
                    else:
                        header.append("◀ ", style="green bold")
                        header.append("server → client", style="green")
                        border_style = "green"

                header.append(" | method: ", style="white")
                header.append(msg.get("method") or "unknown", style="yellow bold")
                header.append(" | ", style="white")
                header.append(time_str, style="grey50")

                if msg.get("message_type") == "response" and msg.get("latency_ms") is not None:
                    latency = msg["latency_ms"]
                    header.append(" | ", style="white")
                    header.append(f"+{latency:.0f}ms", style="magenta bold")

                panel = Panel(
                    syntax_body,
                    title=header,
                    title_align="left",
                    border_style=border_style,
                    safe_box=True,
                )
                panels.append(panel)

            if output:
                with open(output, "w", encoding="utf-8") as f:
                    file_console = Console(file=f, force_terminal=False, color_system=None)
                    for panel in panels:
                        file_console.print(panel)
            else:
                for panel in panels:
                    console.print(panel)

        await db.close()

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        sys.exit(0)


@app.command(name="doctor")
def doctor() -> None:
    """Run diagnostic checks on the environment and database setup."""
    import shutil
    import sqlite3
    import os

    lines = []
    critical_failed = False

    # 1. Python version check
    py_ver = f"{sys.version_info[0]}.{sys.version_info[1]}.{sys.version_info[2]}"
    if sys.version_info >= (3, 11):
        lines.append(Text.assemble(("✓", "green"), f" Python version: {py_ver} (required >=3.11)"))
    else:
        lines.append(
            Text.assemble(
                ("✗", "red"), f" Python version check: Python 3.11+ required, found {py_ver}"
            )
        )
        critical_failed = True

    # 2. SQLite check
    try:
        sqlite_ver = sqlite3.sqlite_version
        ver_parts = [int(x) for x in sqlite_ver.split(".")]
        if ver_parts >= [3, 35, 0]:
            lines.append(Text.assemble(("✓", "green"), f" SQLite version: {sqlite_ver}"))
        else:
            lines.append(
                Text.assemble(
                    ("✗", "red"),
                    f" SQLite version check: SQLite version < 3.35.0 (old), found {sqlite_ver}",
                )
            )
            critical_failed = True
    except ImportError:
        lines.append(Text.assemble(("✗", "red"), " SQLite check: SQLite not available"))
        critical_failed = True
    except Exception as e:
        lines.append(Text.assemble(("✗", "red"), f" SQLite check: SQLite check failed: {e}"))
        critical_failed = True

    # 3. Database directory check
    db_dir = Path.home() / ".mcp-debugger"
    if db_dir.exists():
        if os.access(db_dir, os.W_OK):
            lines.append(Text.assemble(("✓", "green"), f" Database directory: {db_dir} [writable]"))
        else:
            lines.append(
                Text.assemble(
                    ("✗", "red"),
                    f" Database directory: Cannot create ~/.mcp-debugger: permission denied at {db_dir}",
                )
            )
            critical_failed = True
    else:
        lines.append(
            Text.assemble(
                ("✗", "red"),
                f" Database directory: {db_dir} [missing – suggest running: mkdir {db_dir}]",
            )
        )
        critical_failed = True

    # 4. Database file check
    db_file_path = db_dir / "sessions.db"
    if db_file_path.exists():
        # Check permissions
        if os.name != "nt":
            try:
                mode = os.stat(db_file_path).st_mode & 0o777
                if mode == 0o600:
                    lines.append(
                        Text.assemble(
                            ("✓", "green"), f" Database file: {db_file_path} [permissions 600]"
                        )
                    )
                else:
                    lines.append(
                        Text.assemble(
                            ("✗", "yellow"),
                            f" Database file: {db_file_path} [Permissions too open: should be 600, found {oct(mode)[2:]}]",
                        )
                    )
            except Exception as e:
                lines.append(
                    Text.assemble(
                        ("✗", "yellow"),
                        f" Database file check: Failed to check DB file permissions: {e}",
                    )
                )
        else:
            lines.append(Text.assemble(("✓", "green"), f" Database file: {db_file_path} [exists]"))

        # Check schema version
        try:
            conn = sqlite3.connect(db_file_path)
            cursor = conn.cursor()
            cursor.execute("PRAGMA user_version;")
            row = cursor.fetchone()
            user_ver = row[0] if row else 0
            conn.close()

            if user_ver == 1:
                lines.append(Text.assemble(("✓", "green"), f" Database schema version: {user_ver}"))
            else:
                lines.append(
                    Text.assemble(
                        ("✗", "red"),
                        f" Database schema check: Schema version mismatch: expected 1, got {user_ver}",
                    )
                )
                critical_failed = True
        except Exception as e:
            lines.append(Text.assemble(("✗", "red"), f" Database schema check failed: {e}"))
            critical_failed = True
    else:
        lines.append(
            Text.assemble(
                ("✓", "green"),
                " Database file: no database file found yet (will be created on first proxy run)",
            )
        )
        lines.append(Text.assemble(("✓", "green"), " Database schema version: not yet created"))

    # 5. npx check
    npx_path = shutil.which("npx")
    if npx_path:
        lines.append(
            Text.assemble(
                ("✓", "green"), f" npx command found: {npx_path} (for Node.js MCP servers)"
            )
        )
    else:
        lines.append(
            Text.assemble(
                ("✗", "yellow"),
                " npx command check: npx not found – MCP servers requiring Node.js may fail",
            )
        )

    # 6. node check
    node_path = shutil.which("node")
    if node_path:
        lines.append(Text.assemble(("✓", "green"), f" Node.js found: {node_path}"))
    else:
        lines.append(
            Text.assemble(
                ("✗", "yellow"),
                " Node.js not found – some MCP servers require Node.js",
            )
        )

    # 7. git check
    git_path = shutil.which("git")
    if git_path:
        lines.append(Text.assemble(("✓", "green"), f" git command found: {git_path}"))
    else:
        lines.append(Text.assemble(("✓", "green"), " git not found (optional)"))

    # 8. PATH check
    path_dirs = os.environ.get("PATH", "").split(os.pathsep)
    path_summary = ", ".join(path_dirs[:3])
    if len(path_dirs) > 3:
        path_summary += ", ..."
    lines.append(Text.assemble(("✓", "green"), f" PATH includes: {path_summary}"))

    # Render Panel
    panel_content = Text()
    for idx, line in enumerate(lines):
        if idx > 0:
            panel_content.append("\n")
        panel_content.append(line)

    console.print(
        Panel(
            panel_content,
            title="🔍 MCP Debugger Environment Check",
            title_align="left",
            border_style="red" if critical_failed else "green",
            safe_box=True,
        )
    )

    if critical_failed:
        raise typer.Exit(code=1)
    else:
        raise typer.Exit(code=0)


@app.command(name="tools")
def tools(
    session_id: int = typer.Argument(..., help="The ID of the session to view tools for"),
    detail: Optional[str] = typer.Option(
        None,
        "--detail",
        help="Show the full input schema for a specific tool",
    ),
    json_mode: bool = typer.Option(
        False,
        "--json",
        help="Output raw JSON array of tools for scripting",
    ),
) -> None:
    """View discovered tools and their usage schemas/call counts for a session."""

    async def _run() -> None:
        db = Database()
        try:
            await db.connect()
            session = await db.get_session(session_id)
        except (sqlite3.DatabaseError, aiosqlite.DatabaseError):
            console.print(
                f"[red]Error: Database file at {db.db_path} appears to be corrupted or invalid.[/red]"
            )
            console.print(
                "[yellow]Recovery Suggestion: Try deleting or renaming the file to reset the database.[/yellow]"
            )
            sys.exit(1)
        except Exception as e:
            console.print(f"[red]Error connecting to database: {e}[/red]")
            sys.exit(1)

        if not session:
            console.print(f"Session {session_id} not found")
            await db.close()
            sys.exit(1)

        try:
            tools_list = await db.get_tools(session_id)
        except Exception as e:
            console.print(f"[red]Error fetching tools: {e}[/red]")
            await db.close()
            sys.exit(1)

        if not tools_list:
            if json_mode:
                print("[]")
            else:
                console.print("No tools discovered in this session")
            await db.close()
            sys.exit(1)

        # If detailed view requested for a specific tool
        if detail:
            target_tool = next((t for t in tools_list if t["name"] == detail), None)
            if not target_tool:
                console.print(f"Tool {detail} not found in this session")
                await db.close()
                sys.exit(1)

            try:
                schema_dict = json.loads(target_tool["input_schema"])
            except Exception:
                schema_dict = target_tool["input_schema"]

            if json_mode:
                print(json.dumps(schema_dict, indent=2))
            else:
                syntax_schema = Syntax(json.dumps(schema_dict, indent=2), "json")
                console.print(
                    Panel(
                        syntax_schema,
                        title=f"🔧 Tool Schema: {detail}",
                        title_align="left",
                        border_style="magenta",
                        safe_box=True,
                    )
                )
            await db.close()
            return

        # Fetch usage counts
        tools_with_calls = []
        for t in tools_list:
            calls_count = await db.get_tool_usage_count(session_id, t["name"])
            try:
                schema_dict = json.loads(t["input_schema"])
            except Exception:
                schema_dict = t["input_schema"]

            tools_with_calls.append(
                {
                    "name": t["name"],
                    "description": t["description"],
                    "input_schema": schema_dict,
                    "calls": calls_count,
                }
            )

        if json_mode:
            print(json.dumps(tools_with_calls, indent=2))
        else:
            session_name_part = (
                f" ({session['friendly_name']})" if session.get("friendly_name") else ""
            )
            table = Table(
                title=f"Tools discovered in session #{session_id}{session_name_part}",
                border_style="magenta",
            )
            table.add_column("Name", style="cyan bold")
            table.add_column("Description", style="white")
            table.add_column("Calls", justify="right", style="green")

            for tc in tools_with_calls:
                table.add_row(
                    tc["name"],
                    tc["description"] or "—",
                    str(tc["calls"]),
                )
            console.print(table)

        await db.close()

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        sys.exit(0)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
