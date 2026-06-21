import json
import asyncio
import pathlib
from typer.testing import CliRunner

from mcp_debugger.cli import app
from mcp_debugger.storage.database import Database


def _populate_export_session(mock_db_path: str) -> None:
    """Shared helper: create a session with messages and an error."""

    async def _create() -> None:
        db = Database(db_path=mock_db_path)
        await db.connect()
        sid = await db.create_session("export-server", friendly_name="export test")
        await db.log_message(
            session_id=sid,
            direction="client_to_server",
            message={
                "jsonrpc": "2.0",
                "id": "1",
                "method": "initialize",
                "params": {"protocolVersion": "2025-03-26"},
            },
        )
        await db.log_message(
            session_id=sid,
            direction="server_to_client",
            message={
                "jsonrpc": "2.0",
                "id": "1",
                "result": {"protocolVersion": "2025-03-26", "serverInfo": {"name": "t"}},
            },
        )
        await db.log_error(
            session_id=sid,
            message_id=None,
            error_type="protocol",
            error_message="Method not found",
            suggestion="Check spelling",
            error_code=-32601,
        )
        await db.close_session(sid, "completed")
        await db.close()

    asyncio.run(_create())


def test_export_json_stdout(mock_db_path: str, runner: CliRunner) -> None:
    """export --format json prints valid JSON to stdout."""
    _populate_export_session(mock_db_path)
    result = runner.invoke(app, ["export", "1", "--format", "json"])
    assert result.exit_code == 0, result.output
    doc = json.loads(result.stdout)
    assert doc["session"]["id"] == 1
    assert "messages" in doc
    assert "tools" in doc
    assert "errors" in doc
    assert "stats" in doc
    # The error we inserted must appear
    assert any(e["type"] == "protocol" for e in doc["errors"])


def test_export_json_to_file(mock_db_path: str, tmp_path: pathlib.Path, runner: CliRunner) -> None:
    """export --format json --output file.json writes to the given path."""
    _populate_export_session(mock_db_path)
    out_file = str(tmp_path / "session.json")
    result = runner.invoke(app, ["export", "1", "--format", "json", "--output", out_file])
    assert result.exit_code == 0, result.output
    assert "Exported to" in result.stdout
    content = pathlib.Path(out_file).read_text(encoding="utf-8")
    doc = json.loads(content)
    assert doc["session"]["id"] == 1


def test_export_json_pretty(mock_db_path: str, runner: CliRunner) -> None:
    """export --format json --pretty output contains newlines (indented)."""
    _populate_export_session(mock_db_path)
    result = runner.invoke(app, ["export", "1", "--format", "json", "--pretty"])
    assert result.exit_code == 0, result.output
    assert "\n" in result.stdout


def test_export_markdown_stdout(mock_db_path: str, runner: CliRunner) -> None:
    """export --format markdown prints a readable Markdown report."""
    _populate_export_session(mock_db_path)
    result = runner.invoke(app, ["export", "1", "--format", "markdown"])
    assert result.exit_code == 0, result.output
    assert "# MCP Session Report" in result.stdout
    assert "## Metadata" in result.stdout
    assert "## Errors" in result.stdout
    assert "protocol" in result.stdout


def test_export_markdown_include_raw(mock_db_path: str, runner: CliRunner) -> None:
    """export --format markdown --include-raw adds <details> blocks."""
    _populate_export_session(mock_db_path)
    result = runner.invoke(app, ["export", "1", "--format", "markdown", "--include-raw"])
    assert result.exit_code == 0, result.output
    assert "<details>" in result.stdout


def test_export_nonexistent_session(mock_db_path: str, runner: CliRunner) -> None:
    """export with a non-existent session ID exits with code 1."""
    _populate_export_session(mock_db_path)
    result = runner.invoke(app, ["export", "9999", "--format", "json"])
    assert result.exit_code == 1
    assert "not found" in result.output.lower()


def test_export_invalid_format(mock_db_path: str, runner: CliRunner) -> None:
    """export with an unknown format exits with code 1."""
    _populate_export_session(mock_db_path)
    result = runner.invoke(app, ["export", "1", "--format", "csv"])
    assert result.exit_code == 1
    assert "unknown format" in result.output.lower()
