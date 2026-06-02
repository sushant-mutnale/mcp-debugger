"""Tests for CLI commands."""

from typer.testing import CliRunner

from mcp_debugger.cli import app

runner = CliRunner()


def test_version() -> None:
    """Verify that the version command works and returns the correct version."""
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "v0.1.0" in result.stdout
