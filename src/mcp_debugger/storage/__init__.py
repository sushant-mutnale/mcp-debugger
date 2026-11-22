"""Storage package – SQLite and PostgreSQL backends."""

from __future__ import annotations

import os

from mcp_debugger.storage.database import Database
from mcp_debugger.storage.postgres import PostgresDatabase, normalize_postgres_url


def get_database(
    db_path: str | None = None,
    database_url: str | None = None,
) -> Database | PostgresDatabase:
    """Return configured database backend (PostgreSQL if URL is provided, else SQLite)."""
    effective_url = database_url or os.environ.get("MCP_DEBUGGER_DATABASE_URL")
    if not effective_url:
        try:
            from mcp_debugger.config import get_config

            cfg = get_config()
            effective_url = cfg.get("storage.database_url") or cfg.get("database.url")
        except Exception:
            effective_url = None

    if effective_url and any(
        effective_url.strip().startswith(prefix)
        for prefix in ("postgres://", "postgresql://", "postgresql+asyncpg://")
    ):
        return PostgresDatabase(effective_url)

    return Database(db_path=db_path)


__all__ = [
    "Database",
    "PostgresDatabase",
    "get_database",
    "normalize_postgres_url",
]
