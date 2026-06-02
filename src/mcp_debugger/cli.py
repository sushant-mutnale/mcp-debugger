"""CLI commands for MCP Debugger."""

import typer
from rich.console import Console

from mcp_debugger import __version__

app = typer.Typer(
    name="mcp-debugger",
    help="CLI debugger for the Model Context Protocol (MCP)",
    no_args_is_help=True,
)
console = Console()


@app.callback()
def main() -> None:
    """MCP Debugger - CLI debugger for the Model Context Protocol (MCP)."""


@app.command(name="version")
def version() -> None:
    """Print the version of MCP Debugger."""
    console.print(
        f"[bold violet]MCP Debugger[/bold violet] [cyan]v{__version__}[/cyan] 🚀"
    )


if __name__ == "__main__":
    app()
