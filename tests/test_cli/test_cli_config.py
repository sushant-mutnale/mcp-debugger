"""Unit tests for config subcommands in mcp-debugger CLI."""

from typer.testing import CliRunner

from mcp_debugger.cli import app
import mcp_debugger.config as _cfg_mod


def test_cli_version(runner: CliRunner) -> None:
    # Test version subcommand
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "mcp-debugger" in result.stdout


def test_cli_config_init(runner: CliRunner, tmp_path, monkeypatch) -> None:
    # Set default_config_path mock
    mock_path = tmp_path / "config.toml"
    monkeypatch.setattr(_cfg_mod, "default_config_path", lambda: mock_path)

    # First init should succeed
    result = runner.invoke(app, ["config", "init"])
    assert result.exit_code == 0
    assert "created at" in result.stdout.lower()
    assert mock_path.exists()

    # Second init without --force should prompt
    # Simulate user saying "no"
    result = runner.invoke(app, ["config", "init"], input="n\n")
    assert result.exit_code == 0
    assert "aborted" in result.stdout.lower()

    # Second init with --force should succeed without prompt
    result = runner.invoke(app, ["config", "init", "--force"])
    assert result.exit_code == 0
    assert "created at" in result.stdout.lower()


def test_cli_config_get_set_unset(runner: CliRunner, tmp_path, monkeypatch) -> None:
    mock_path = tmp_path / "config.toml"
    monkeypatch.setattr(_cfg_mod, "default_config_path", lambda: mock_path)
    # Reset config file first
    runner.invoke(app, ["config", "init", "--force"])

    # 1. Get existing key
    result = runner.invoke(app, ["config", "get", "replay.timeout"])
    assert result.exit_code == 0
    assert "replay.timeout" in result.stdout
    assert "5000" in result.stdout

    # 2. Get missing key
    result = runner.invoke(app, ["config", "get", "replay.nonexistent"])
    assert result.exit_code == 1
    assert "not found" in result.stdout.lower()

    # 3. Set key
    result = runner.invoke(app, ["config", "set", "replay.timeout", "8000"])
    assert result.exit_code == 0
    assert "replay.timeout = 8000" in result.stdout

    # Verify key was set
    result = runner.invoke(app, ["config", "get", "replay.timeout"])
    assert result.exit_code == 0
    assert "8000" in result.stdout

    # 4. Unset key (custom alias key not in defaults)
    result = runner.invoke(app, ["config", "set", "aliases.myserver", "npx -y server"])
    assert result.exit_code == 0

    result = runner.invoke(app, ["config", "unset", "aliases.myserver"])
    assert result.exit_code == 0
    assert "removed from config" in result.stdout

    # Unset missing key
    result = runner.invoke(app, ["config", "unset", "aliases.myserver"])
    assert result.exit_code == 0
    assert "was not found" in result.stdout


def test_cli_config_list_and_reset(runner: CliRunner, tmp_path, monkeypatch) -> None:
    mock_path = tmp_path / "config.toml"
    monkeypatch.setattr(_cfg_mod, "default_config_path", lambda: mock_path)
    runner.invoke(app, ["config", "init", "--force"])

    # List config
    result = runner.invoke(app, ["config", "list"])
    assert result.exit_code == 0
    assert "replay" in result.stdout
    assert "timeout" in result.stdout

    # Reset config - user abort
    result = runner.invoke(app, ["config", "reset"], input="n\n")
    assert result.exit_code == 0
    assert "aborted" in result.stdout.lower()

    # Reset config - user confirm
    result = runner.invoke(app, ["config", "reset"], input="y\n")
    assert result.exit_code == 0
    assert "reset to defaults" in result.stdout.lower()

    # Reset config with --force
    result = runner.invoke(app, ["config", "reset", "--force"])
    assert result.exit_code == 0
    assert "reset to defaults" in result.stdout.lower()


def test_cli_config_list_nested(runner: CliRunner, monkeypatch) -> None:
    """Verify nested configuration tables are rendered correctly in list subcommand."""
    from mcp_debugger.config import Config

    mock_data = {
        "section_a": {"nested_key": {"sub_key": "sub_value"}},
        "section_b": "not-a-dict-so-it-is-skipped",
    }
    # Mock Config.all method
    monkeypatch.setattr(Config, "all", lambda self: mock_data)

    result = runner.invoke(app, ["config", "list"])
    assert result.exit_code == 0
    assert "section_a" in result.stdout
    assert "nested_key.sub_key" in result.stdout
    assert "'sub_value'" in result.stdout
