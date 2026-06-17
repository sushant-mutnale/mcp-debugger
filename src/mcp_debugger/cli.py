"""CLI entry point for mcp-debugger."""

import asyncio
from datetime import datetime, timezone
import io
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, List, Optional, Tuple

import aiosqlite
import typer
from rich.console import Console, Group
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from mcp_debugger.proxy.stdio_proxy import StdioProxy
from mcp_debugger.storage.database import Database
from mcp_debugger.protocol.error_classifier import ErrorClassifier
from mcp_debugger.analytics import (
    aggregate_session_stats,
    compare_sessions_stats,
    generate_sparkline,
    generate_bar_chart,
)

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


# ---------------------------------------------------------------------------
# Config command group
# ---------------------------------------------------------------------------

config_app = typer.Typer(help="Manage mcp-debugger configuration.")
app.add_typer(config_app, name="config")


@config_app.command(name="init")
def config_init(
    force: bool = typer.Option(False, "--force", help="Overwrite existing config without prompting"),
) -> None:
    """Create the default config file (~/.mcp-debugger/config.toml)."""
    from mcp_debugger.config import Config, default_config_path
    path = default_config_path()
    if path.exists() and not force:
        overwrite = typer.confirm(f"Config file already exists at {path}. Overwrite?", default=False)
        if not overwrite:
            console.print("[yellow]Aborted.[/yellow]")
            raise typer.Exit(0)
    cfg = Config(path=path)
    cfg.reset()
    console.print(f"[green]✓ Config file created at {path}[/green]")


@config_app.command(name="get")
def config_get(
    key: str = typer.Argument(..., help="Config key in dot-notation, e.g. replay.timeout"),
) -> None:
    """Show the value of a config key."""
    from mcp_debugger.config import Config, default_config_path
    cfg = Config(path=default_config_path())
    cfg.load()
    value = cfg.get(key)
    if value is None:
        console.print(f"[yellow]Key '{key}' not found.[/yellow]")
        raise typer.Exit(1)
    console.print(f"{key} = {value!r}")


@config_app.command(name="set")
def config_set(
    key: str = typer.Argument(..., help="Config key in dot-notation, e.g. replay.timeout"),
    value: str = typer.Argument(..., help="Value to store (auto-converted to int/bool/float if possible)"),
) -> None:
    """Set a config value and save to disk."""
    from mcp_debugger.config import Config, default_config_path
    cfg = Config(path=default_config_path())
    cfg.load()
    cfg.set(key, value)
    new_val = cfg.get(key)
    console.print(f"[green]✓[/green] {key} = {new_val!r}")


@config_app.command(name="unset")
def config_unset(
    key: str = typer.Argument(..., help="Config key to remove (reverts to default)"),
) -> None:
    """Remove a config key (reverts to the hardcoded default)."""
    from mcp_debugger.config import Config, default_config_path
    cfg = Config(path=default_config_path())
    cfg.load()
    removed = cfg.unset(key)
    if removed:
        console.print(f"[green]✓[/green] '{key}' removed from config.")
    else:
        console.print(f"[yellow]Key '{key}' was not found in config.[/yellow]")


@config_app.command(name="list")
def config_list() -> None:
    """Show all config values in a formatted table."""
    from mcp_debugger.config import Config, default_config_path
    cfg = Config(path=default_config_path())
    cfg.load()
    data = cfg.all()

    table = Table(title="mcp-debugger configuration", show_header=True, header_style="bold cyan")
    table.add_column("Section", style="bold")
    table.add_column("Key")
    table.add_column("Value", style="green")

    for section, section_val in data.items():
        if not isinstance(section_val, dict):
            continue
        first = True
        for k, v in section_val.items():
            if isinstance(v, dict):
                # nested (profiles sub-tables)
                for sub_k, sub_v in v.items():
                    table.add_row(
                        section if first else "",
                        f"{k}.{sub_k}",
                        repr(sub_v),
                    )
                    first = False
            else:
                table.add_row(section if first else "", k, repr(v))
                first = False

    console.print(table)
    console.print(f"\n[dim]Config file: {default_config_path()}[/dim]")


@config_app.command(name="reset")
def config_reset(
    force: bool = typer.Option(False, "--force", help="Reset without prompting"),
) -> None:
    """Reset config to factory defaults."""
    from mcp_debugger.config import Config, default_config_path
    if not force:
        confirm = typer.confirm("Reset config to defaults? This will overwrite your current config.", default=False)
        if not confirm:
            console.print("[yellow]Aborted.[/yellow]")
            raise typer.Exit(0)
    cfg = Config(path=default_config_path())
    cfg.reset()
    console.print("[green]✓ Config reset to defaults.[/green]")




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
            try:
                errors = await db.get_errors(session_id)
                error_map = {err["message_id"]: err for err in errors if err.get("message_id") is not None}
            except Exception:
                error_map = {}
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

                err_info = error_map.get(msg.get("id"))
                if err_info is None:
                    classifier = ErrorClassifier()
                    classification = classifier.classify(envelope)
                    if classification is not None:
                        cat, msg_text, sug = classification
                        err_info = {
                            "error_type": cat,
                            "error_message": msg_text,
                            "suggestion": sug,
                        }

                time_str = "unknown"
                if msg.get("timestamp") is not None:
                    try:
                        dt = datetime.fromtimestamp(msg["timestamp"] / 1000.0)
                        time_str = dt.strftime("%H:%M:%S.%f")[:-3]
                    except Exception:
                        time_str = str(msg["timestamp"])

                direction_str = msg.get("direction")
                is_error = (msg.get("error") is not None) or (err_info is not None)

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

                if err_info is not None:
                    err_type = err_info.get("error_type") or "unknown"
                    badge = f" | [{err_type.upper()} ERROR]"
                    header.append(badge, style="red bold")

                header.append(" | method: ", style="white")
                header.append(msg.get("method") or "unknown", style="yellow bold")
                header.append(" | ", style="white")
                header.append(time_str, style="grey50")

                if msg.get("message_type") == "response" and msg.get("latency_ms") is not None:
                    latency = msg["latency_ms"]
                    header.append(" | ", style="white")
                    header.append(f"+{latency:.0f}ms", style="magenta bold")

                if err_info is not None and err_info.get("suggestion"):
                    suggestion_text = Text(f"\n💡 Suggestion: {err_info['suggestion']}", style="yellow italic")
                    panel_content = Group(syntax_body, suggestion_text)
                else:
                    panel_content = Group(syntax_body)

                panel = Panel(
                    panel_content,
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


@app.command(name="errors")
def list_errors(
    session_id: int = typer.Argument(..., help="The ID of the session to check for errors"),
    category: Optional[str] = typer.Option(
        None,
        "--category",
        help="Filter errors by category (protocol, tool_execution, timeout, connection, unknown)",
    ),
    json_mode: bool = typer.Option(
        False,
        "--json",
        help="Output raw JSON array of error objects",
    ),
) -> None:
    """List and filter classified errors from a specific debugging session."""

    async def _run() -> None:
        db = Database()
        try:
            await db.connect()
            session = await db.get_session(session_id)
        except (sqlite3.DatabaseError, aiosqlite.DatabaseError):
            console.print(
                f"[red]Error: Database file at {db.db_path} appears to be corrupted or invalid.[/red]"
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
            errors = await db.get_errors(session_id)
        except Exception as e:
            console.print(f"[red]Error fetching errors: {e}[/red]")
            await db.close()
            sys.exit(1)

        # If category is provided, filter the errors list
        if category:
            cat_lower = category.lower().strip()
            errors = [e for e in errors if e.get("error_type", "").lower() == cat_lower]

        if json_mode:
            # Format errors list to standard JSON format
            json_errors = []
            for err in errors:
                json_errors.append({
                    "id": err["id"],
                    "message_id": err["message_id"],
                    "error_code": err["error_code"],
                    "error_type": err["error_type"],
                    "error_message": err["error_message"],
                    "suggestion": err["suggestion"],
                    "stack_trace": err["stack_trace"],
                    "classified_at": err["classified_at"],
                })
            print(json.dumps(json_errors, indent=2))
        else:
            if not errors:
                console.print(f"[yellow]No classified errors found for session {session_id}[/yellow]")
            else:
                table = Table(title=f"Classified Errors for Session {session_id}", border_style="red")
                table.add_column("ID", justify="right", style="cyan")
                table.add_column("Type", style="magenta bold")
                table.add_column("Message", style="white")
                table.add_column("Suggestion", style="yellow italic")

                for err in errors:
                    table.add_row(
                        str(err["id"]),
                        str(err["error_type"]).upper(),
                        str(err["error_message"]),
                        str(err["suggestion"] or "—"),
                      )
                console.print(table)

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

    # 9. Config file check
    from mcp_debugger.config import Config, default_config_path
    cfg_path = default_config_path()
    if not cfg_path.exists():
        lines.append(Text.assemble(("✓", "green"), f" Config file: {cfg_path} [not found – using defaults]"))
    else:
        try:
            _cfg_check = Config(path=cfg_path)
            _cfg_check.load()
            lines.append(Text.assemble(("✓", "green"), f" Config file: {cfg_path} [valid]"))
        except Exception as cfg_err:
            lines.append(
                Text.assemble(("✗", "yellow"), f" Config file: {cfg_path} [invalid: {cfg_err}]")
            )


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


def calculate_compliance_score(results: List[Any]) -> Tuple[int, int, int]:
    """Calculates the compliance score based on 5 critical rule categories:

    1. jsonrpc_version
    2. envelope_type (envelope_type, response_envelope, method_format)
    3. initialize_first
    4. handshake_order (severity="critical")
    5. tool_schema_validity (tool_schema_validity, tool_input_schema_format)

    Returns (score_percentage, passed_count, total_count)
    """
    # If there is a server startup or connection error, score is 0%
    if any(
        r.rule_name in ("server_startup", "server_connection", "handshake_timeout") and not r.passed
        for r in results
    ):
        return 0, 0, 5

    failed_rules = set()
    for r in results:
        if not r.passed and r.severity == "critical":
            if r.rule_name == "jsonrpc_version":
                failed_rules.add("jsonrpc_version")
            elif r.rule_name in ("envelope_type", "response_envelope", "method_format"):
                failed_rules.add("envelope_type")
            elif r.rule_name == "initialize_first":
                failed_rules.add("initialize_first")
            elif r.rule_name == "handshake_order":
                failed_rules.add("handshake_order")
            elif r.rule_name in ("tool_schema_validity", "tool_input_schema_format"):
                failed_rules.add("tool_schema_validity")

    passed_count = 5 - len(failed_rules)
    percentage = int((passed_count / 5) * 100)
    return percentage, passed_count, 5


@app.command(name="validate")
def validate(
    session_id: Optional[int] = typer.Argument(
        None, help="The ID of the recorded session to validate"
    ),
    server: Optional[str] = typer.Option(
        None, "--server", "-s", help="Launch a live MCP server command and test it"
    ),
    json_mode: bool = typer.Option(
        False, "--json", help="Output raw JSON array of validation results"
    ),
) -> None:
    """Validate MCP protocol compliance of a live server or recorded session."""

    async def _run() -> None:
        if session_id is not None and server is not None:
            console.print(
                "[red]Error: Please specify either a session_id or --server, not both.[/red]"
            )
            sys.exit(1)
        if session_id is None and server is None:
            console.print(
                "[red]Error: Please specify a session_id to validate or run a live server validation with --server.[/red]"
            )
            sys.exit(1)

        from mcp_debugger.protocol.validator import ProtocolValidator
        from mcp_debugger.validate_live import run_live_validation

        if server is not None:
            if not json_mode:
                console.print(f"🔍 Validating live server: {server}")

            try:
                sid, results = await run_live_validation(server)
            except Exception as e:
                console.print(f"[red]Error during live validation: {e}[/red]")
                sys.exit(1)
        else:
            if session_id is None:
                console.print("[red]Error: session_id is required.[/red]")
                sys.exit(1)

            db = Database()
            try:
                await db.connect()
                session = await db.get_session(session_id)
            except Exception as e:
                console.print(f"[red]Error connecting to database: {e}[/red]")
                sys.exit(1)

            if not session:
                console.print(f"[red]Error: Session #{session_id} not found.[/red]")
                await db.close()
                sys.exit(1)

            if not json_mode:
                console.print(f"🔍 Validating recorded session #{session_id}")

            try:
                validator = ProtocolValidator()
                results = await validator.validate_session(session_id, db)
            except Exception as e:
                console.print(f"[red]Error validating session: {e}[/red]")
                await db.close()
                sys.exit(1)
            finally:
                await db.close()

        # Render results
        if json_mode:
            json_results = []
            for r in results:
                try:
                    json_results.append(r.model_dump())
                except AttributeError:
                    # pyrefly: ignore [deprecated]
                    json_results.append(r.dict())
            print(json.dumps(json_results, indent=2))
        else:
            table = Table(
                title="Validation Results",
                border_style="magenta",
            )
            table.add_column("Rule", style="cyan bold")
            table.add_column("Severity", style="white")
            table.add_column("Message", style="white")

            has_critical = False
            critical_count = 0
            warning_count = 0

            for r in results:
                if not r.passed:
                    if r.severity == "critical":
                        severity_text = "[red]🔴 CRIT[/red]"
                        has_critical = True
                        critical_count += 1
                    elif r.severity == "warning":
                        severity_text = "[yellow]🟡 WARN[/yellow]"
                        warning_count += 1
                    else:
                        severity_text = "[blue]🔵 INFO[/blue]"
                else:
                    severity_text = "[green]✓ PASS[/green]"

                msg_detail = r.message
                if r.suggestion:
                    msg_detail += f"\n[yellow]→ Suggestion: {r.suggestion}[/yellow]"

                table.add_row(r.rule_name, severity_text, msg_detail)

            console.print(table)

            score, passed, total = calculate_compliance_score(results)

            if has_critical:
                console.print(
                    f"\n[red]Overall compliance: {critical_count} critical failures, {warning_count} warnings.[/red]"
                )
                console.print(f"Compliance score: {score}% ({passed}/{total} critical rules passed)")
                sys.exit(1)
            else:
                console.print(
                    f"\n[green]Overall compliance: 0 critical failures, {warning_count} warnings.[/green]"
                )
                console.print(f"Compliance score: {score}% ({passed}/{total} critical rules passed)")
                sys.exit(0)

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        sys.exit(0)


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
                    str(tc["name"]),
                    str(tc["description"] or "—"),
                    str(tc["calls"]),
                )
            console.print(table)

        await db.close()

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        sys.exit(0)


def generate_markdown_report(stats_data: Any, limit: int) -> str:
    duration_str = "N/A"
    if stats_data.duration_seconds is not None:
        m, s = divmod(stats_data.duration_seconds, 60)
        duration_str = f"{m}m {s}s" if m > 0 else f"{s}s"

    lines = [
        f"# Session Statistics Report - Session #{stats_data.session_id}",
        "",
        f"- **Friendly Name**: {stats_data.friendly_name or '—'}",
        f"- **Server Command**: `{stats_data.server_command}`",
        f"- **Status**: {stats_data.status}",
        f"- **Duration**: {duration_str}",
        f"- **Total Messages**: {stats_data.total_messages} ({stats_data.client_to_server_count} client-to-server, {stats_data.server_to_client_count} server-to-client)",
        "",
        "## Top Tools",
        "| Tool | Calls | Avg Latency | Error Rate |",
        "| :--- | :---: | :---: | :---: |",
    ]
    
    for tool in stats_data.top_tools[:limit]:
        avg_lat = f"{tool.avg_latency_ms:.1f}ms" if tool.avg_latency_ms is not None else "—"
        err_rate_str = f"{tool.error_rate * 100:.0f}%"
        if tool.errors_count > 0:
            err_rate_str += f" ({tool.errors_count} error{'s' if tool.errors_count > 1 else ''})"
        lines.append(f"| {tool.name} | {tool.calls} | {avg_lat} | {err_rate_str} |")

    lines.extend([
        "",
        "## Latency Metrics",
        f"- **Min Latency**: {f'{stats_data.latency_min:.1f}ms' if stats_data.latency_min is not None else 'N/A'}",
        f"- **Max Latency**: {f'{stats_data.latency_max:.1f}ms' if stats_data.latency_max is not None else 'N/A'}",
        f"- **Avg Latency**: {f'{stats_data.latency_avg:.1f}ms' if stats_data.latency_avg is not None else 'N/A'}",
        "",
        "## Errors by Category",
    ])
    
    if not stats_data.errors_by_category:
        lines.append("No errors recorded.")
    else:
        for cat, count in stats_data.errors_by_category.items():
            lines.append(f"- **{cat}**: {count}")

    lines.extend([
        "",
        "## Method Distribution",
        "| Method | Count | Percentage |",
        "| :--- | :---: | :---: |",
    ])
    
    total_methods = sum(stats_data.method_distribution.values())
    for method, count in sorted(stats_data.method_distribution.items(), key=lambda x: x[1], reverse=True):
        pct = (count / total_methods) * 100 if total_methods > 0 else 0.0
        lines.append(f"| {method} | {count} | {pct:.1f}% |")

    return "\n".join(lines)


@app.command(name="stats")
def stats(
    session_id: int = typer.Argument(..., help="The ID of the session to view statistics for"),
    limit: int = typer.Option(
        10,
        "--limit",
        help="Number of top tools to show",
    ),
    json_mode: bool = typer.Option(
        False,
        "--json",
        help="Output raw statistics as JSON",
    ),
    output: Optional[str] = typer.Option(
        None,
        "--output",
        help="Write report to a file (Markdown or JSON)",
    ),
) -> None:
    """Display a comprehensive statistical dashboard for a single session."""
    async def _run() -> None:
        db = Database()
        try:
            await db.connect()
        except Exception as e:
            console.print(f"[red]Error connecting to database: {e}[/red]")
            sys.exit(1)

        try:
            stats_data = await aggregate_session_stats(db, session_id)
        except ValueError as e:
            console.print(f"[red]Error: {e}[/red]")
            await db.close()
            sys.exit(1)
        except Exception as e:
            console.print(f"[red]Error aggregating statistics: {e}[/red]")
            await db.close()
            sys.exit(1)

        await db.close()

        # Handle --json mode
        if json_mode:
            stats_json = stats_data.model_dump_json(indent=2)
            print(stats_json)
            if output:
                try:
                    Path(output).write_text(stats_json, encoding="utf-8")
                except Exception as e:
                    console.print(f"[red]Error writing to output file: {e}[/red]")
            return

        # Handle file output if specified (and not in JSON mode)
        if output:
            try:
                out_path = Path(output)
                if out_path.suffix == ".json":
                    out_path.write_text(stats_data.model_dump_json(indent=2), encoding="utf-8")
                else:
                    # Generate markdown report
                    md = generate_markdown_report(stats_data, limit)
                    out_path.write_text(md, encoding="utf-8")
            except Exception as e:
                console.print(f"[red]Error writing output file: {e}[/red]")

        # RENDER TO TERMINAL
        # Session Header Panel
        status_style = "green" if stats_data.status == "completed" else ("red" if stats_data.status == "error" else "yellow")
        
        duration_str = "N/A"
        if stats_data.duration_seconds is not None:
            m, s = divmod(stats_data.duration_seconds, 60)
            duration_str = f"{m}m {s}s" if m > 0 else f"{s}s"

        header_lines = [
            f"Server: [cyan]{stats_data.server_command}[/cyan]",
            f"Status: [{status_style}]{stats_data.status}[/{status_style}]",
            f"Started: {stats_data.started_at or 'N/A'} | Ended: {stats_data.ended_at or 'Ongoing'} | Duration: {duration_str}",
            f"Messages: {stats_data.total_messages} total ({stats_data.client_to_server_count} → server, {stats_data.server_to_client_count} ← client)",
        ]
        
        title_friendly = f" - \"{stats_data.friendly_name}\"" if stats_data.friendly_name else ""
        console.print(
            Panel(
                "\n".join(header_lines),
                title=f"Session #{stats_data.session_id}{title_friendly}",
                border_style="blue",
                safe_box=True,
            )
        )

        # Top Tools Table
        console.print("\n📊 [bold]Top Tools[/bold]")
        if not stats_data.top_tools:
            console.print("No tools called in this session.")
        else:
            table = Table(border_style="magenta")
            table.add_column("Tool", style="cyan bold")
            table.add_column("Calls", justify="right")
            table.add_column("Avg Latency", justify="right")
            table.add_column("Error Rate", justify="right")

            for tool in stats_data.top_tools[:limit]:
                avg_lat = f"{tool.avg_latency_ms:.1f}ms" if tool.avg_latency_ms is not None else "—"
                err_rate_val = tool.error_rate * 100
                err_rate_str = f"{err_rate_val:.0f}%"
                if tool.errors_count > 0:
                    err_rate_str += f" ({tool.errors_count} error{'s' if tool.errors_count > 1 else ''})"
                err_style = "red" if tool.errors_count > 0 else "green"
                
                table.add_row(
                    tool.name,
                    str(tool.calls),
                    avg_lat,
                    f"[{err_style}]{err_rate_str}[/{err_style}]",
                )
            console.print(table)

        # Latency Trend
        console.print("\n📈 [bold]Latency Trend[/bold] (response time over time)")
        if not stats_data.latency_trend:
            console.print("No latency data available.")
        else:
            spark = generate_sparkline(stats_data.latency_trend, width=30)
            min_l = f"{stats_data.latency_min:.1f}ms" if stats_data.latency_min is not None else "N/A"
            max_l = f"{stats_data.latency_max:.1f}ms" if stats_data.latency_max is not None else "N/A"
            avg_l = f"{stats_data.latency_avg:.1f}ms" if stats_data.latency_avg is not None else "N/A"
            console.print(f"{spark} (min {min_l}, max {max_l}, avg {avg_l})")

        # Errors by Category
        console.print("\n⚠️ [bold]Errors by Category[/bold]")
        if not stats_data.errors_by_category:
            console.print("No errors recorded.")
        else:
            err_chart = generate_bar_chart(stats_data.errors_by_category, max_width=20)
            for label, count, pct, bar_str in err_chart:
                console.print(f"{label}: {count} [red]{bar_str}[/red] ({pct*100:.0f}%)")

        # Method Distribution
        console.print("\n🔁 [bold]Method Distribution[/bold]")
        if not stats_data.method_distribution:
            console.print("No methods recorded.")
        else:
            method_chart = generate_bar_chart(stats_data.method_distribution, max_width=20)
            for label, count, pct, bar_str in method_chart:
                console.print(f"{label}: {count} [blue]{bar_str}[/blue] ({pct*100:.0f}%)")

        # Error Trend Sparkline
        console.print("\n📈 [bold]Error Trend[/bold] (error density over time)")
        if not stats_data.error_trend:
            console.print("No responses recorded to track errors.")
        else:
            err_spark = generate_sparkline([float(x) for x in stats_data.error_trend], width=30)
            total_err = sum(stats_data.errors_by_category.values())
            console.print(f"{err_spark} ({total_err} total errors)")

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        sys.exit(0)


@app.command(name="compare")
def compare(
    session_id_a: int = typer.Argument(..., help="The ID of the baseline session (old)"),
    session_id_b: int = typer.Argument(..., help="The ID of the target session to compare against (new)"),
    json_mode: bool = typer.Option(
        False,
        "--json",
        help="Output raw comparison statistics as JSON",
    ),
) -> None:
    """Highlight differences between two debugging sessions."""
    async def _run() -> None:
        db = Database()
        try:
            await db.connect()
        except Exception as e:
            console.print(f"[red]Error connecting to database: {e}[/red]")
            sys.exit(1)

        try:
            stats_a = await aggregate_session_stats(db, session_id_a)
            stats_b = await aggregate_session_stats(db, session_id_b)
        except ValueError as e:
            console.print(f"[red]Error: {e}[/red]")
            await db.close()
            sys.exit(1)
        except Exception as e:
            console.print(f"[red]Error aggregating session statistics: {e}[/red]")
            await db.close()
            sys.exit(1)

        await db.close()

        comparison = compare_sessions_stats(stats_a, stats_b)

        if json_mode:
            print(comparison.model_dump_json(indent=2))
            return

        # RENDER COMPARISON TO TERMINAL
        console.print(f"[bold]Comparing session #{session_id_a} (old) vs #{session_id_b} (new)[/bold]\n")

        # Duration change
        dur_a_str = f"{stats_a.duration_seconds}s" if stats_a.duration_seconds is not None else "N/A"
        dur_b_str = f"{stats_b.duration_seconds}s" if stats_b.duration_seconds is not None else "N/A"
        
        dur_color = "white"
        if comparison.duration_change_pct is not None:
            if comparison.duration_change_pct < 0:
                dur_color = "green"
            elif comparison.duration_change_pct > 0:
                dur_color = "red"
        
        console.print(f"Duration: {dur_a_str} → {dur_b_str} ([{dur_color}]{comparison.duration_change_str}[/{dur_color}])")

        # Messages change
        msg_diff_str = f"{comparison.messages_change_abs:+d} messages" if comparison.messages_change_abs != 0 else "no change"
        console.print(f"Total messages: {comparison.messages_a} → {comparison.messages_b} ({msg_diff_str})\n")

        # Tool Call Changes Table
        console.print("📊 [bold]Tool Call Changes[/bold]")
        if not comparison.tool_changes:
            console.print("No tool call changes recorded.")
        else:
            table = Table(border_style="magenta")
            table.add_column("Tool", style="cyan bold")
            table.add_column("Old Calls", justify="right")
            table.add_column("New Calls", justify="right")
            table.add_column("Change", justify="right")
            table.add_column("Avg Latency (Old → New)", justify="right")

            for tc in comparison.tool_changes:
                # Color code change string
                if "new" in tc.change_str:
                    change_style = "green bold"
                elif "removed" in tc.change_str:
                    change_style = "red bold"
                elif "+" in tc.change_str:
                    change_style = "blue"
                elif "-" in tc.change_str:
                    change_style = "yellow"
                else:
                    change_style = "white"

                lat_a = f"{tc.avg_latency_a:.1f}ms" if tc.avg_latency_a is not None else "—"
                lat_b = f"{tc.avg_latency_b:.1f}ms" if tc.avg_latency_b is not None else "—"
                
                lat_change_str = ""
                if tc.avg_latency_change_pct is not None:
                    if tc.avg_latency_change_pct < 0:
                        lat_change_str = f" [green](↓ {abs(tc.avg_latency_change_pct):.0f}% faster)[/green]"
                    elif tc.avg_latency_change_pct > 0:
                        lat_change_str = f" [red](↑ {abs(tc.avg_latency_change_pct):.0f}% slower)[/red]"
                
                table.add_row(
                    tc.name,
                    str(tc.calls_a),
                    str(tc.calls_b),
                    f"[{change_style}]{tc.change_str}[/{change_style}]",
                    f"{lat_a} → {lat_b}{lat_change_str}",
                )
            console.print(table)

        # Error Rate Change
        console.print("\n⚠️ [bold]Error Rate Change[/bold]")
        err_color = "white"
        if "improvement" in comparison.error_rate_change_str:
            err_color = "green"
        elif "regression" in comparison.error_rate_change_str:
            err_color = "red"
        
        console.print(
            f"Old: {comparison.error_rate_a:.1f}% ({comparison.errors_a} errors) → "
            f"New: {comparison.error_rate_b:.1f}% ({comparison.errors_b} errors) "
            f"([{err_color}]{comparison.error_rate_change_str}[/{err_color}])\n"
        )

        # Dynamic Summary statement
        summary_parts = []
        if comparison.duration_change_pct is not None and comparison.duration_change_pct < -5:
            summary_parts.append("is faster")
        elif comparison.duration_change_pct is not None and comparison.duration_change_pct > 5:
            summary_parts.append("is slower")

        if comparison.errors_b < comparison.errors_a:
            summary_parts.append("has fewer errors")
        elif comparison.errors_b > comparison.errors_a:
            summary_parts.append("has more errors")

        summary_text = ""
        if summary_parts:
            summary_text = f"Session #{session_id_b} " + " and ".join(summary_parts) + "."
        else:
            summary_text = f"Session #{session_id_b} has similar performance and error rates compared to #{session_id_a}."

        # Add warnings about removed tools or slower tools
        warnings = []
        for tc in comparison.tool_changes:
            if "removed" in tc.change_str:
                warnings.append(f"tool '{tc.name}' was removed")
            elif tc.avg_latency_change_pct is not None and tc.avg_latency_change_pct > 20:
                warnings.append(f"tool '{tc.name}' got significantly slower (+{tc.avg_latency_change_pct:.0f}%)")

        if warnings:
            summary_text += " [yellow]Verify changes: " + ", ".join(warnings) + ".[/yellow]"

        console.print(f"💡 [bold]Summary:[/bold] {summary_text}")

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        sys.exit(0)


@app.command(name="export")
def export(
    session_id: int = typer.Argument(..., help="The ID of the session to export"),
    format: str = typer.Option(
        "json",
        "--format",
        help="Export format: json | markdown | otlp",
    ),
    output: Optional[str] = typer.Option(
        None,
        "--output",
        help="Write to file instead of stdout (json / markdown formats)",
    ),
    pretty: bool = typer.Option(
        False,
        "--pretty",
        help="Pretty-print JSON / indent markdown raw blocks",
    ),
    include_raw: bool = typer.Option(
        False,
        "--include-raw",
        help="Include raw message JSON in markdown <details> blocks",
    ),
    endpoint: str = typer.Option(
        "http://localhost:4317",
        "--endpoint",
        help="OTLP collector endpoint (otlp format only)",
    ),
    insecure: bool = typer.Option(
        True,
        "--insecure",
        help="Disable TLS (for local OTLP testing)",
    ),
    service_name: str = typer.Option(
        "mcp-debugger",
        "--service-name",
        help="Service name for OTLP traces",
    ),
    limit: Optional[int] = typer.Option(
        None,
        "--limit",
        help="Max messages to export (useful for large sessions with otlp)",
    ),
) -> None:
    """Export session data as JSON, Markdown, or OpenTelemetry (OTLP) traces."""

    # Config fallbacks: export.default_format and export.pretty_json
    from mcp_debugger.config import Config, default_config_path
    _cfg = Config(path=default_config_path())
    _cfg.load()
    # Only apply config default when the user didn't explicitly pass --format
    # (typer default is "json" so we can't distinguish; treat "json" as config-eligible)
    effective_format = format if format != "json" else str(_cfg.get("export.default_format", "json"))
    effective_pretty = pretty or bool(_cfg.get("export.pretty_json", False))

    fmt = effective_format.lower().strip()
    if fmt not in {"json", "markdown", "otlp"}:
        console.print(f"[red]Error: unknown format '{effective_format}'. Choose json, markdown, or otlp.[/red]")
        sys.exit(1)

    async def _run() -> None:
        db = Database()
        try:
            await db.connect()
        except Exception as e:
            console.print(f"[red]Error connecting to database: {e}[/red]")
            sys.exit(1)

        session = await db.get_session(session_id)
        if not session:
            console.print(f"[red]Error: Session #{session_id} not found.[/red]")
            await db.close()
            sys.exit(1)

        messages = await db.get_messages(session_id, limit=limit)
        tools = await db.get_tools(session_id)
        errors = await db.get_errors(session_id)

        try:
            from mcp_debugger.analytics import aggregate_session_stats as _agg
            stats = await _agg(db, session_id)
        except Exception as e:
            console.print(f"[red]Error computing session stats: {e}[/red]")
            await db.close()
            sys.exit(1)

        await db.close()

        # ---- OTLP -----------------------------------------------------------
        if fmt == "otlp":
            try:
                from mcp_debugger.exporters.otlp_exporter import OTLPExporter
            except ImportError as exc:
                console.print(f"[red]{exc}[/red]")
                sys.exit(1)
            try:
                exporter_otlp = OTLPExporter(
                    endpoint=endpoint,
                    insecure=insecure,
                    service_name=service_name,
                    limit=limit,
                )
                span_count = exporter_otlp.export(dict(session), messages)
                console.print(
                    f"[green]Exported {span_count} span(s) to {endpoint}[/green]"
                )
            except Exception as e:
                console.print(f"[yellow]Warning: OTLP export failed: {e}[/yellow]")
            return

        # ---- JSON / Markdown ------------------------------------------------
        if fmt == "json":
            from mcp_debugger.exporters.json_exporter import JSONExporter
            exporter_obj: Any = JSONExporter(pretty=effective_pretty, include_raw=include_raw)
        else:
            from mcp_debugger.exporters.markdown_exporter import MarkdownExporter
            exporter_obj = MarkdownExporter(include_raw=include_raw, pretty=effective_pretty)

        if output:
            out_path = Path(output)
            try:
                with out_path.open("w", encoding="utf-8") as f:
                    exporter_obj.export(dict(session), messages, tools, errors, stats, f)
                console.print(f"[green]Exported to {out_path.resolve()}[/green]")
            except Exception as e:
                console.print(f"[red]Error writing to {output}: {e}[/red]")
                sys.exit(1)
        else:
            buf = io.StringIO()
            exporter_obj.export(dict(session), messages, tools, errors, stats, buf)
            print(buf.getvalue())

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        sys.exit(0)


@app.command(name="replay")
def replay(
    session_id: int = typer.Argument(
        ..., help="ID of the recorded session to replay"
    ),
    server: Optional[str] = typer.Option(
        None, "--server", "-s", help="Command to launch the target server (overrides --alias and config)"
    ),
    alias: Optional[str] = typer.Option(
        None, "--alias", "-a", help="Server alias defined in config [aliases] section"
    ),
    timeout: Optional[int] = typer.Option(
        None, "--timeout", help="Timeout in milliseconds per request-response pair"
    ),
    max_messages: Optional[int] = typer.Option(
        None, "--max-messages", help="Maximum number of client messages to replay"
    ),
    filter_method: Optional[str] = typer.Option(
        None, "--filter-method", help="Only replay messages with this method name"
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Show all messages with diffs (even matches)"
    ),
    json_mode: bool = typer.Option(
        False, "--json", help="Output raw JSON report"
    ),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o", help="Write output to a file"
    ),
    save: bool = typer.Option(
        False, "--save", help="Save replay results to the replays database table"
    ),
    no_diff: bool = typer.Option(
        False, "--no-diff", help="Skip detailed diff output (only show summary)"
    ),
    otlp_export: bool = typer.Option(
        False, "--otlp-export", help="Export replay results to an OTLP collector (requires mcp-debugger[otlp])"
    ),
    otlp_endpoint: Optional[str] = typer.Option(
        None, "--otlp-endpoint", help="OTLP gRPC collector endpoint"
    ),
    otlp_insecure: bool = typer.Option(
        True, "--otlp-insecure/--otlp-tls", help="Disable TLS for local OTLP collectors"
    ),
    otlp_service_name: Optional[str] = typer.Option(
        None, "--otlp-service-name", help="Service name for OTLP traces"
    ),
) -> None:
    """Replay client messages from a recorded session against a target server."""

    # ------------------------------------------------------------------
    # Config fallbacks (CLI flags override, then config, then hardcoded defaults)
    # ------------------------------------------------------------------
    from mcp_debugger.config import Config, default_config_path
    _cfg = Config(path=default_config_path())
    _cfg.load()

    # Resolve server: --server > --alias > config.replay.default_server
    effective_server = server
    if effective_server is None and alias is not None:
        effective_server = _cfg.resolve_alias(alias)
        if effective_server is None:
            console.print(f"[red]Alias '{alias}' not found in config [aliases] section.[/red]")
            sys.exit(1)
    if effective_server is None:
        effective_server = _cfg.get("replay.default_server", "") or None
    if not effective_server:
        console.print(
            "[red]Error: No server specified. Use --server, --alias, or set replay.default_server in config.[/red]"
        )
        sys.exit(1)

    # Numeric and boolean fallbacks
    effective_timeout: int = timeout if timeout is not None else int(_cfg.get("replay.timeout", 5000))
    effective_save: bool = save or bool(_cfg.get("replay.auto_save", False))
    effective_no_diff: bool = no_diff or bool(_cfg.get("replay.diff_only", False))
    effective_otlp_export: bool = otlp_export or bool(_cfg.get("replay.otlp_export", False))
    effective_otlp_endpoint: str = otlp_endpoint or str(_cfg.get("replay.otlp_endpoint", "http://localhost:4317"))
    effective_otlp_service_name: str = otlp_service_name or str(_cfg.get("replay.otlp_service_name", "mcp-debugger"))

    def format_payload(val: Any) -> str:
        if val is None:
            return "None"
        try:
            return json.dumps(val, indent=2)
        except Exception:
            return str(val)

    def indent_text(text: str, spaces: int = 2) -> str:
        indent = " " * spaces
        return "\n".join(indent + line for line in text.splitlines())

    async def _run() -> None:
        db = Database()
        try:
            await db.connect()
        except Exception as e:
            console.print(f"[red]Error connecting to database: {e}[/red]")
            sys.exit(1)

        session = await db.get_session(session_id)
        if not session:
            console.print(f"[red]Error: Session #{session_id} not found.[/red]")
            await db.close()
            sys.exit(1)

        from mcp_debugger.replay.engine import ReplayEngine
        engine = ReplayEngine(db)

        # Set up progress bar if not in JSON mode and output is terminal
        progress_bar = None
        task_id = None

        if not json_mode:
            from rich.progress import Progress, BarColumn, TextColumn, TimeElapsedColumn
            progress_bar = Progress(
                TextColumn(f"Replaying session {session_id}..."),
                BarColumn(),
                TextColumn("{task.completed}/{task.total} ({task.percentage:>3.0f}%)"),
                TimeElapsedColumn(),
                console=console,
            )
            progress_bar.start()
            task_id = progress_bar.add_task("replaying", total=0)

        def on_message_replayed(current: int, total: int) -> None:
            if progress_bar and task_id is not None:
                progress_bar.update(task_id, completed=current, total=total)

        # Replay the messages
        replay_mode = "exact"
        message_filter = None
        if filter_method:
            replay_mode = "selective"
            message_filter = [filter_method]

        result = await engine.replay(
            session_id=session_id,
            target_server_command=effective_server,
            timeout_ms=effective_timeout,
            replay_mode=replay_mode,
            message_filter=message_filter,
            persist=effective_save,
            max_messages=max_messages,
            on_message_replayed=on_message_replayed,
        )

        if progress_bar:
            progress_bar.stop()

        await db.close()

        # Check for target server failed to start (command not found / invalid command)
        failed_to_start = False
        for msg in result.messages:
            if msg.error and "Failed to start server" in msg.error:
                failed_to_start = True
                break

        if failed_to_start:
            # Print error and exit with code 2
            console.print(f"[red]Error: Target server failed to start: {result.messages[0].error}[/red]")
            sys.exit(2)

        # Check if server crashed during replay
        crashed_msg = None
        for msg in result.messages:
            if msg.error and ("terminated" in msg.error.lower() or "write error" in msg.error.lower()):
                crashed_msg = msg
                break

        if crashed_msg is not None:
            console.print(f"[red]Error: Server crashed during message #{crashed_msg.original_message_id}: {crashed_msg.error}[/red]")
            sys.exit(2)

        # Check if server timed out
        if result.timed_out > 0:
            # Print timeout details and exit with code 2
            timed_out_msgs = [m for m in result.messages if m.error and "Timeout" in m.error]
            if timed_out_msgs:
                console.print(f"[red]Error: Server timed out during message #{timed_out_msgs[0].original_message_id}: {timed_out_msgs[0].error}[/red]")
            sys.exit(2)

        # Setup redirection for output
        if output:
            capture_file = io.StringIO()
            run_console = Console(file=capture_file, force_terminal=True, color_system="truecolor")
        else:
            run_console = console

        # Calculate counts
        successful_matches = sum(1 for m in result.messages if m.matches)
        mismatches = result.mismatched_responses
        timeouts = result.timed_out
        errors = result.failed_responses
        duration = (result.ended_at - result.started_at).total_seconds()

        if json_mode:
            # Build and serialize JSON report
            json_report = {
                "session_id": session_id,
                "source_server_command": session["server_command"],
                "target_server_command": effective_server,
                "started_at": result.started_at.isoformat().replace("+00:00", "Z"),
                "ended_at": result.ended_at.isoformat().replace("+00:00", "Z"),
                "duration_seconds": round(duration, 2),
                "summary": {
                    "total": result.total_messages_replayed,
                    "matches": successful_matches,
                    "mismatches": mismatches,
                    "timeouts": timeouts,
                    "errors": errors,
                },
                "messages": [
                    {
                        "original_message_id": m.original_message_id,
                        "method": m.method,
                        "matched": m.matches,
                        "diff": [d.model_dump() for d in m.diff] if m.diff else None,
                    }
                    for m in result.messages
                ]
            }
            json_str = json.dumps(json_report, indent=2)
            if output:
                try:
                    Path(output).write_text(json_str, encoding="utf-8")
                except Exception as e:
                    console.print(f"[red]Error writing output to {output}: {e}[/red]")
                    sys.exit(1)
            else:
                print(json_str)
        else:
            # Terminal Output (Default)
            summary_lines = [
                f"Replay of Session #{session_id}",
                f"Source server: {session['server_command']}",
                f"Target server: {effective_server}",
                f"Duration: {duration:.2f} seconds",
                "─" * 65,
                f"Total messages replayed: {result.total_messages_replayed}",
                f"[green]✓ Successful matches: {successful_matches}[/green]",
                f"[red]✗ Mismatches: {mismatches}[/red]" if mismatches else f"✗ Mismatches: {mismatches}",
                f"[yellow]⏱ Timeouts: {timeouts}[/yellow]" if timeouts else f"⏱ Timeouts: {timeouts}",
                f"[red]❌ Errors: {errors}[/red]" if errors else f"❌ Errors: {errors}",
            ]
            summary_panel = Panel(
                "\n".join(summary_lines),
                title="Replay Summary",
                border_style="blue",
            )
            run_console.print(summary_panel)

            # Print messages detailed reports
            for m in result.messages:
                if m.matches:
                    if verbose:
                        run_console.print(f"[green]✓[/green] Message #{m.original_message_id}: {m.method}")
                else:
                    run_console.print(f"\n[red]✗[/red] Message #{m.original_message_id}: {m.method} (client → server)")
                    if not effective_no_diff:
                        # Show mismatch details
                        if m.method == "tools/call" and m.request_sent:
                            params = m.request_sent.get("params", {})
                            if isinstance(params, dict):
                                tool_name = params.get("name")
                                tool_args = params.get("arguments")
                                if tool_name:
                                    run_console.print(f"Tool: {tool_name}")
                                if tool_args is not None:
                                    run_console.print(f"Arguments: {json.dumps(tool_args)}")

                        run_console.print("\nOriginal response:")
                        run_console.print(indent_text(format_payload(m.original_response), 2))
                        run_console.print("\nReplayed response:")
                        run_console.print(indent_text(format_payload(m.replayed_response), 2))

                        if m.diff_text:
                            run_console.print("\nDifferences:")
                            run_console.print(indent_text(m.diff_text, 2))
                        run_console.print()

            if effective_no_diff:
                mismatched_ids = [m.original_message_id for m in result.messages if not m.matches]
                if mismatched_ids:
                    run_console.print(f"\nMismatched Message IDs: {mismatched_ids}")

            if effective_save and result.replay_id is not None and result.replay_id != -1:
                run_console.print(f"\nReplay saved as replay ID {result.replay_id}. Use 'mcp-debugger replay show {result.replay_id}' to view later.")

            if output:
                try:
                    Path(output).write_text(capture_file.getvalue(), encoding="utf-8")
                except Exception as e:
                    console.print(f"[red]Error writing output to {output}: {e}[/red]")
                    sys.exit(1)

        # Exit codes:
        # 0 if all responses match
        # 1 if any mismatch (i.e. mismatches > 0)

        # --- OTLP export (optional, non-blocking) ---
        if effective_otlp_export:
            try:
                from mcp_debugger.exporters.otlp_replay_exporter import OTLPReplayExporter
                exporter_otlp = OTLPReplayExporter(
                    endpoint=effective_otlp_endpoint,
                    insecure=otlp_insecure,
                    service_name=effective_otlp_service_name,
                )
                span_count = exporter_otlp.export(result)
                console.print(f"[dim]OTLP: exported {span_count} spans to {effective_otlp_endpoint}[/dim]")
            except ImportError as ie:
                console.print(f"[yellow]Warning: {ie}[/yellow]")
            except Exception as oe:
                console.print(f"[yellow]Warning: OTLP export failed: {oe}[/yellow]")

        if mismatches > 0:
            sys.exit(1)
        else:
            sys.exit(0)

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        sys.exit(0)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
