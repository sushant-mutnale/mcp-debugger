"""CLI entry point for mcp-debugger."""

import asyncio
import sys
import typer
from rich.console import Console
from rich.panel import Panel

from mcp_debugger.storage.database import Database
from mcp_debugger.proxy.stdio_proxy import StdioProxy

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


@app.command(name="proxy")
def proxy(
    server: str = typer.Option(..., "--server", "-s", help="The command to launch the target MCP server"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose debug logging"),
) -> None:
    """Launch the transparent stdio proxy and log session traffic to SQLite."""
    async def _run() -> None:
        db = Database()
        await db.connect()

        # Create a new session
        session_id = await db.create_session(server_command=server)
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


def main() -> None:
    app()
