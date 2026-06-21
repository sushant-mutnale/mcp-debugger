import asyncio
from typing import Optional
from unittest.mock import AsyncMock, patch
from typer.testing import CliRunner

from mcp_debugger.cli import app
from mcp_debugger.storage.database import Database


def test_proxy_command_with_name(mock_db_path: str, runner: CliRunner) -> None:
    """Verify that proxy command accepts and records the session friendly name."""
    with patch("mcp_debugger.cli.StdioProxy.run", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = 0
        result = runner.invoke(app, ["proxy", "--server", "cat", "--name", "test-friendly-name"])
        assert result.exit_code == 0

    async def verify() -> Optional[str]:
        db = Database(db_path=mock_db_path)
        await db.connect()
        sessions = await db.get_sessions()
        await db.close()
        if sessions:
            val = sessions[0]["friendly_name"]
            return str(val) if val is not None else None
        return None

    name = asyncio.run(verify())
    assert name == "test-friendly-name"
