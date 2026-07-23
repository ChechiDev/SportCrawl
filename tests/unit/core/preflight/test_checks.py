"""Unit tests for core.preflight.checks — RED phase."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from core.preflight.checks import (
    check_alembic_initialized,
    check_alembic_revision,
    check_db_reachable,
    check_schemas_exist,
    check_seed_data,
    check_stale_queue,
    check_tables_exist,
)

DSN = "postgresql://user:pass@localhost:5432/testdb"


def _mock_conn(fetchval=None, fetchrow=None, fetch=None):
    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=fetchval)
    conn.fetchrow = AsyncMock(return_value=fetchrow)
    conn.fetch = AsyncMock(return_value=fetch if fetch is not None else [])
    conn.close = AsyncMock()
    return conn


# ── check_db_reachable ──────────────────────────────────────────────────────


class TestCheckDbReachable:
    async def test_pass_when_connect_succeeds(self):
        conn = _mock_conn()
        with patch("asyncpg.connect", AsyncMock(return_value=conn)):
            result = await check_db_reachable(DSN)
        assert result.passed is True
        assert result.fatal is True

    async def test_fail_when_connect_raises(self):
        with patch("asyncpg.connect", AsyncMock(side_effect=Exception("refused"))):
            result = await check_db_reachable(DSN)
        assert result.passed is False
        assert result.fatal is True
        assert "Cannot connect" in result.detail


# ── check_alembic_initialized ───────────────────────────────────────────────


class TestCheckAlembicInitialized:
    async def test_pass_when_table_exists(self):
        conn = _mock_conn(fetchval=True)
        with patch("asyncpg.connect", AsyncMock(return_value=conn)):
            result = await check_alembic_initialized(DSN)
        assert result.passed is True
        assert result.fatal is True

    async def test_fail_when_table_missing(self):
        conn = _mock_conn(fetchval=False)
        with patch("asyncpg.connect", AsyncMock(return_value=conn)):
            result = await check_alembic_initialized(DSN)
        assert result.passed is False
        assert "migrations have never run" in result.detail


# ── check_alembic_revision ──────────────────────────────────────────────────


class TestCheckAlembicRevision:
    async def test_pass_when_revision_matches(self):
        conn = _mock_conn(fetchval="p14g")
        with patch("asyncpg.connect", AsyncMock(return_value=conn)):
            result = await check_alembic_revision(DSN, "p14g")
        assert result.passed is True

    async def test_fail_when_revision_differs(self):
        conn = _mock_conn(fetchval="abc123")
        with patch("asyncpg.connect", AsyncMock(return_value=conn)):
            result = await check_alembic_revision(DSN, "p14g")
        assert result.passed is False
        assert result.fatal is True
        assert "abc123" in result.detail
        assert "p14g" in result.detail


# ── check_schemas_exist ─────────────────────────────────────────────────────


class TestCheckSchemasExist:
    async def test_pass_when_both_schemas_present(self):
        rows = [MagicMock(), MagicMock()]  # 2 rows
        conn = _mock_conn(fetch=rows)
        with patch("asyncpg.connect", AsyncMock(return_value=conn)):
            result = await check_schemas_exist(DSN)
        assert result.passed is True

    async def test_fail_when_schema_missing(self):
        rows = [MagicMock()]  # only 1
        conn = _mock_conn(fetch=rows)
        with patch("asyncpg.connect", AsyncMock(return_value=conn)):
            result = await check_schemas_exist(DSN)
        assert result.passed is False
        assert result.fatal is True


# ── check_tables_exist ──────────────────────────────────────────────────────


class TestCheckTablesExist:
    async def test_pass_countries_all_present(self):
        # fetchval returns non-None for all to_regclass calls → all tables exist
        conn = _mock_conn(fetchval="sch_shared.tbl_countries")
        with patch("asyncpg.connect", AsyncMock(return_value=conn)):
            result = await check_tables_exist(DSN, "countries")
        assert result.passed is True

    async def test_fail_when_table_missing(self):
        # fetchval returns None for at least one table
        conn = AsyncMock()
        conn.close = AsyncMock()
        # Return None for first call (missing table)
        conn.fetchval = AsyncMock(return_value=None)
        with patch("asyncpg.connect", AsyncMock(return_value=conn)):
            result = await check_tables_exist(DSN, "countries")
        assert result.passed is False
        assert result.fatal is True
        assert "missing" in result.detail.lower()

    async def test_player_info_phase_includes_extra_tables(self):
        conn = _mock_conn(fetchval="exists")
        with patch("asyncpg.connect", AsyncMock(return_value=conn)):
            result = await check_tables_exist(DSN, "player_info")
        assert result.passed is True


# ── check_seed_data ─────────────────────────────────────────────────────────


class TestCheckSeedData:
    async def test_pass_players_phase_when_countries_exist(self):
        conn = _mock_conn(fetchval=100)
        with patch("asyncpg.connect", AsyncMock(return_value=conn)):
            result = await check_seed_data(DSN, "players")
        assert result.passed is True

    async def test_fail_players_phase_when_no_countries(self):
        conn = _mock_conn(fetchval=0)
        with patch("asyncpg.connect", AsyncMock(return_value=conn)):
            result = await check_seed_data(DSN, "players")
        assert result.passed is False
        assert result.fatal is True

    async def test_pass_player_info_phase_when_players_exist(self):
        conn = _mock_conn(fetchval=5000)
        with patch("asyncpg.connect", AsyncMock(return_value=conn)):
            result = await check_seed_data(DSN, "player_info")
        assert result.passed is True

    async def test_fail_player_info_phase_when_no_players(self):
        conn = _mock_conn(fetchval=0)
        with patch("asyncpg.connect", AsyncMock(return_value=conn)):
            result = await check_seed_data(DSN, "player_info")
        assert result.passed is False


# ── check_stale_queue ───────────────────────────────────────────────────────


class TestCheckStaleQueue:
    async def test_pass_when_no_stale_jobs(self):
        conn = _mock_conn(fetchval=0)
        with patch("asyncpg.connect", AsyncMock(return_value=conn)):
            result = await check_stale_queue(DSN)
        assert result.passed is True
        assert result.fatal is False

    async def test_fail_when_stale_jobs_exist(self):
        conn = _mock_conn(fetchval=3)
        with patch("asyncpg.connect", AsyncMock(return_value=conn)):
            result = await check_stale_queue(DSN)
        assert result.passed is False
        assert result.fatal is False  # non-fatal!
        assert "3" in result.detail
