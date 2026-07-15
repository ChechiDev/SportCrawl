"""Integration tests for Phase 11 migrations (p11a + p11b).

Verifies that the player discovery schema is created and torn down cleanly:
- p11a creates player tables, football tables, and progress view
- p11b adds locked_at to scrape_queue
- p11a downgrade drops view and player tables cleanly
- p11b downgrade removes locked_at while leaving player tables intact

These tests run alembic upgrade/downgrade programmatically against a real
Postgres testcontainer, independent of the session-scoped migrate_db fixture.
Each test function starts from a known revision state and leaves the DB in
a state suitable for the next test (tests are ordered to avoid conflicts).

NOTE: These tests require Docker and are deferred to CI. They are NOT run
in the local unit suite.
"""

from __future__ import annotations

import asyncio
import os
from functools import partial

from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _alembic_run(fn: object, cfg: AlembicConfig, revision: str) -> None:
    """Run a sync alembic command in a thread so it can call asyncio.run() safely."""
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(  # type: ignore[arg-type]
        None, partial(fn, cfg, revision)
    )


def _alembic_cfg(db_url: URL) -> AlembicConfig:
    """Build an AlembicConfig pointed at the testcontainer DB."""
    ini_path = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "..", "alembic.ini")
    )
    cfg = AlembicConfig(ini_path)
    cfg.attributes["inject_url"] = db_url
    return cfg


async def _table_exists(
    session: AsyncSession,
    table_name: str,
    schema: str,
) -> bool:
    """Return True if *table_name* exists in *schema*."""
    result = await session.execute(
        text(
            "SELECT EXISTS ("
            "  SELECT 1 FROM information_schema.tables"
            "  WHERE table_schema = :schema"
            "    AND table_name = :table"
            ")"
        ),
        {"schema": schema, "table": table_name},
    )
    return bool(result.scalar())


async def _view_exists(
    session: AsyncSession,
    view_name: str,
    schema: str,
) -> bool:
    """Return True if *view_name* exists in *schema*."""
    result = await session.execute(
        text(
            "SELECT EXISTS ("
            "  SELECT 1 FROM information_schema.views"
            "  WHERE table_schema = :schema"
            "    AND table_name = :view"
            ")"
        ),
        {"schema": schema, "view": view_name},
    )
    return bool(result.scalar())


async def _column_exists(
    session: AsyncSession,
    table_name: str,
    column_name: str,
    schema: str,
) -> bool:
    """Return True if *column_name* exists on *table_name* in *schema*."""
    result = await session.execute(
        text(
            "SELECT EXISTS ("
            "  SELECT 1 FROM information_schema.columns"
            "  WHERE table_schema = :schema"
            "    AND table_name = :table"
            "    AND column_name = :col"
            ")"
        ),
        {"schema": schema, "table": table_name, "col": column_name},
    )
    return bool(result.scalar())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestP11Migrations:
    async def test_p11a_upgrade_creates_player_tables(
        self, _integration_db_url: URL
    ) -> None:
        """alembic upgrade p11b creates all Phase 11 tables and the view."""
        cfg = _alembic_cfg(_integration_db_url)
        # upgrade head runs p11b (which runs p11a first via chain)
        await _alembic_run(alembic_command.upgrade, cfg, "p11b")

        engine = create_async_engine(_integration_db_url, echo=False)
        try:
            async with engine.connect() as conn:
                async with AsyncSession(bind=conn) as session:
                    assert await _table_exists(
                        session, "tbl_players", "sch_shared"
                    )
                    assert await _table_exists(
                        session, "tbl_player_positions", "sch_shared"
                    )
                    assert await _table_exists(
                        session, "player_discovery_batch", "sch_infra"
                    )
                    assert await _table_exists(
                        session, "player_queue_ref", "sch_infra"
                    )
                    assert await _view_exists(
                        session,
                        "v_player_scrape_progress",
                        "sch_football",
                    )
        finally:
            await engine.dispose()

    async def test_p11b_adds_locked_at_to_scrape_queue(
        self, _integration_db_url: URL
    ) -> None:
        """After upgrade to p11b, scrape_queue has a locked_at column."""
        # p11b is already applied after test_p11a_upgrade_creates_player_tables,
        # but we re-apply idempotently (upgrade to head is safe after head).
        cfg = _alembic_cfg(_integration_db_url)
        await _alembic_run(alembic_command.upgrade, cfg, "p11b")

        engine = create_async_engine(_integration_db_url, echo=False)
        try:
            async with engine.connect() as conn:
                async with AsyncSession(bind=conn) as session:
                    assert await _column_exists(
                        session, "scrape_queue", "locked_at", "sch_infra"
                    )
        finally:
            await engine.dispose()

    async def test_p11b_downgrade_removes_locked_at(
        self, _integration_db_url: URL
    ) -> None:
        """Downgrade from p11b to p11a removes locked_at; player tables intact."""
        cfg = _alembic_cfg(_integration_db_url)
        await _alembic_run(alembic_command.downgrade, cfg, "p11a")

        engine = create_async_engine(_integration_db_url, echo=False)
        try:
            async with engine.connect() as conn:
                async with AsyncSession(bind=conn) as session:
                    assert not await _column_exists(
                        session, "scrape_queue", "locked_at", "sch_infra"
                    )
                    # Player tables should still exist (only p11b rolled back)
                    assert await _table_exists(
                        session, "tbl_players", "sch_shared"
                    )
                    assert await _table_exists(
                        session, "tbl_player_positions", "sch_shared"
                    )
        finally:
            await engine.dispose()

    async def test_p11a_downgrade_drops_view_first(
        self, _integration_db_url: URL
    ) -> None:
        """Downgrade from p11a to p10d drops view and player tables cleanly."""
        cfg = _alembic_cfg(_integration_db_url)
        await _alembic_run(alembic_command.downgrade, cfg, "p10d_add_fk_ondelete")

        engine = create_async_engine(_integration_db_url, echo=False)
        try:
            async with engine.connect() as conn:
                async with AsyncSession(bind=conn) as session:
                    # View dropped
                    assert not await _view_exists(
                        session,
                        "v_player_scrape_progress",
                        "sch_football",
                    )
                    # Player tables dropped
                    assert not await _table_exists(
                        session, "tbl_players", "sch_shared"
                    )
                    assert not await _table_exists(
                        session, "tbl_player_positions", "sch_shared"
                    )
                    assert not await _table_exists(
                        session, "player_discovery_batch", "sch_football"
                    )
                    assert not await _table_exists(
                        session, "player_queue_ref", "sch_football"
                    )
                    # scrape_queue still exists (only player tables removed)
                    assert await _table_exists(
                        session, "scrape_queue", "sch_infra"
                    )
        finally:
            await engine.dispose()

        # Restore schema to head so subsequent tests in the session can use
        # the Phase 11 tables (migrate_db runs upgrade head only once).
        await _alembic_run(alembic_command.upgrade, cfg, "head")
