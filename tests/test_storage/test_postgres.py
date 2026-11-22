"""Unit and mock integration tests for PostgreSQL team storage backend."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_debugger.storage import get_database
from mcp_debugger.storage.database import Database
from mcp_debugger.storage.postgres import PostgresDatabase, normalize_postgres_url


def test_normalize_postgres_url() -> None:
    """Postgres URL normalization strips asyncpg dialect prefix for asyncpg driver."""
    url1 = "postgresql+asyncpg://admin:secret@pg.company.internal:5432/mcp_traces"
    assert normalize_postgres_url(url1) == "postgresql://admin:secret@pg.company.internal:5432/mcp_traces"

    url2 = "postgres://user:pass@localhost:5432/mydb"
    assert normalize_postgres_url(url2) == "postgresql://user:pass@localhost:5432/mydb"

    url3 = "postgresql://user:pass@localhost:5432/mydb"
    assert normalize_postgres_url(url3) == "postgresql://user:pass@localhost:5432/mydb"


def test_database_selection_fallback_and_env(monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory) -> None:
    """Database selector returns SQLite by default and Postgres when configured."""
    # 1. Default fallback to SQLite
    monkeypatch.delenv("MCP_DEBUGGER_DATABASE_URL", raising=False)
    db_default = get_database()
    assert isinstance(db_default, Database)
    assert not isinstance(db_default, PostgresDatabase)

    # 2. Environment variable triggers Postgres backend
    pg_url = "postgresql://user:pass@localhost:5432/testdb"
    monkeypatch.setenv("MCP_DEBUGGER_DATABASE_URL", pg_url)
    db_pg = get_database()
    assert isinstance(db_pg, PostgresDatabase)
    assert db_pg.database_url == "postgresql://user:pass@localhost:5432/testdb"


def test_missing_asyncpg_dependency_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Helpful ImportError is raised if asyncpg is not installed."""
    with patch.dict("sys.modules", {"asyncpg": None}):
        pg_db = PostgresDatabase("postgresql://user:pass@localhost:5432/testdb")
        with pytest.raises(ImportError) as exc_info:
            import asyncio
            asyncio.run(pg_db.connect())
        assert "asyncpg" in str(exc_info.value).lower()
        assert "mcp-debugger[postgres]" in str(exc_info.value)


@pytest.mark.asyncio
async def test_postgres_schema_creation_and_lifecycle() -> None:
    """connect() initializes tables and close() cleans up pool."""
    mock_pool = MagicMock()
    mock_conn = AsyncMock()
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
    mock_pool.close = AsyncMock()
    mock_pool.close = AsyncMock()

    mock_asyncpg = MagicMock()
    mock_asyncpg.create_pool = AsyncMock(return_value=mock_pool)

    with patch.dict("sys.modules", {"asyncpg": mock_asyncpg}):
        pg_db = PostgresDatabase("postgresql://user:pass@localhost:5432/testdb")
        await pg_db.connect()

        # Verify pool creation
        mock_asyncpg.create_pool.assert_awaited_once_with(
            "postgresql://user:pass@localhost:5432/testdb",
            min_size=1,
            max_size=10,
        )

        # Verify schema table execution (sessions, messages, steps, agents, attributions)
        executed_sqls = [call.args[0] for call in mock_conn.execute.await_args_list]
        combined_sql = " ".join(executed_sqls).lower()
        assert "create table if not exists sessions" in combined_sql
        assert "create table if not exists messages" in combined_sql
        assert "create table if not exists steps" in combined_sql
        assert "create table if not exists agents" in combined_sql
        assert "create table if not exists attributions" in combined_sql

        await pg_db.close()
        mock_pool.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_postgres_crud_operations() -> None:
    """PostgresDatabase CRUD methods execute parameterized SQL queries."""
    mock_pool = MagicMock()
    mock_conn = AsyncMock()
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
    mock_pool.close = AsyncMock()

    # Setup fetchrow return values
    mock_conn.fetchval.side_effect = [
        10,  # create_session
        101,  # log_message
        1,  # log_step
        5,  # create_agent
        20,  # log_attribution
    ]
    mock_conn.fetchrow.side_effect = [
        {"id": 10, "session_uuid": "uuid-123", "server_command": "npx server", "status": "running"},
        {"id": 5, "name": "PlannerAgent", "role": "Lead", "parent_agent_id": None},
        {"id": 20, "session_id": 10, "poc_step_index": 1, "failure_category": "agent"},
    ]
    mock_conn.fetch.side_effect = [
        [{"id": 101, "session_id": 10, "direction": "client_to_server", "method": "tools/list"}],
        [{"id": 1, "session_id": 10, "step_index": 1, "step_type": "thought"}],
        [{"id": 5, "name": "PlannerAgent", "role": "Lead", "parent_agent_id": None}],
    ]

    mock_asyncpg = MagicMock()
    mock_asyncpg.create_pool = AsyncMock(return_value=mock_pool)

    with patch.dict("sys.modules", {"asyncpg": mock_asyncpg}):
        pg_db = PostgresDatabase("postgresql://user:pass@localhost:5432/testdb")
        await pg_db.connect()

        # 1. create_session & get_session
        sid = await pg_db.create_session("npx server", friendly_name="test")
        assert sid == 10
        session = await pg_db.get_session(sid)
        assert session is not None
        assert session["id"] == 10

        # 2. log_message & get_messages
        mid = await pg_db.log_message(
            sid,
            "client_to_server",
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
        assert mid == 101
        messages = await pg_db.get_messages(sid)
        assert len(messages) == 1
        assert messages[0]["method"] == "tools/list"

        # 3. log_step & get_steps
        step_id = await pg_db.log_step(
            session_id=sid,
            step_index=1,
            step_type="thought",
            tokens_input=100,
            tokens_output=50,
        )
        assert step_id == 1
        steps = await pg_db.get_steps(sid)
        assert len(steps) == 1

        # 4. create_agent, get_agent, & get_agents
        aid = await pg_db.create_agent(session_id=sid, name="PlannerAgent", role="Lead")
        assert aid == 5
        agent = await pg_db.get_agent(aid)
        assert agent is not None
        assert agent["name"] == "PlannerAgent"
        agents = await pg_db.get_agents(sid)
        assert len(agents) == 1

        # 5. log_attribution & get_attribution
        att_id = await pg_db.log_attribution(
            session_id=sid,
            poc_step_index=1,
            failure_category="agent",
            root_cause_explanation="Reasoning error",
        )
        assert att_id == 20
        attribution = await pg_db.get_attribution(sid)
        assert attribution is not None
        assert attribution["failure_category"] == "agent"

        await pg_db.close()
