import sys
from pathlib import Path
from typing import AsyncGenerator, Generator
import pytest
from typer.testing import CliRunner

from mcp_debugger.storage.database import Database

# Ensure src is on the python path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


@pytest.fixture
def temp_db_path(tmp_path: Path) -> Generator[Path, None, None]:
    """Provide a path for a temporary database file."""
    db_file = tmp_path / "test_sessions.db"
    yield db_file
    # Cleanup file if it exists after test
    if db_file.exists():
        try:
            db_file.unlink()
        except OSError:
            pass


@pytest.fixture
async def temp_db(temp_db_path: Path) -> AsyncGenerator[Database, None]:
    """Fixture that returns a connected Database instance and closes/cleans up afterwards."""
    db = Database(db_path=str(temp_db_path))
    await db.connect()
    yield db
    await db.close()


@pytest.fixture
def runner() -> CliRunner:
    """Fixture for Typer CliRunner."""
    return CliRunner()


@pytest.fixture
def mock_db_path(tmp_path: Path) -> Generator[str, None, None]:
    """Fixture to mock the Database path to use a temporary file for isolation."""
    from typing import Any, Optional
    from unittest.mock import patch

    temp_db_file = tmp_path / "test_sessions.db"
    original_init = Database.__init__

    def mock_init(self: Any, db_path: Optional[str] = None) -> None:
        original_init(self, db_path=str(temp_db_file))

    with patch("mcp_debugger.storage.database.Database.__init__", mock_init):
        yield str(temp_db_file)
