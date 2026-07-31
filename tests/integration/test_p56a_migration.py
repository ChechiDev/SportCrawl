"""Integration tests for migration p56a.

Covers: player_url lifecycle indexes and fn_notify_all_due.
"""
from __future__ import annotations

import asyncio

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


def _alembic_cfg(db_url) -> Config:
    import os

    ini_path = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "..", "alembic.ini")
    )
    cfg = Config(ini_path)
    cfg.attributes["inject_url"] = db_url
    return cfg


async def _run_alembic(fn, cfg, revision: str) -> None:
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, fn, cfg, revision)


class TestP56aMigration:
    async def test_upgrade_creates_pending_predicates(self, _integration_db_url):
        cfg = _alembic_cfg(_integration_db_url)
        # Guard: ensure we are above p55a before downgrading (prior tests may have
        # left the DB at an older revision, making the downgrade target invalid).
        await _run_alembic(command.upgrade, cfg, "head")
        # downgrade to p55a first
        await _run_alembic(command.downgrade, cfg, "p55a")
        try:
            # upgrade to p56a
            await _run_alembic(command.upgrade, cfg, "p56a")

            engine = create_async_engine(_integration_db_url, echo=False)
            try:
                async with engine.connect() as conn:
                    result = await conn.execute(
                        text(
                            "SELECT indexname, indexdef FROM pg_indexes"
                            " WHERE schemaname = 'sch_fbref_backend'"
                            "   AND indexname LIKE '%_due'"
                        )
                    )
                    rows = result.fetchall()
                    names = [r[0] for r in rows]
                    assert len(rows) == 5, (
                        f"Expected 5 *_due indexes, got {len(rows)}: {names}"
                    )
                    for indexname, indexdef in rows:
                        assert "PENDING" in indexdef, (
                            f"Index {indexname} predicate does not include"
                            f" PENDING: {indexdef}"
                        )
            finally:
                await engine.dispose()
        finally:
            # Always restore to head
            await _run_alembic(command.upgrade, cfg, "head")

    async def test_fn_notify_all_due_updated(self, _integration_db_url):
        cfg = _alembic_cfg(_integration_db_url)
        await _run_alembic(command.upgrade, cfg, "head")
        await _run_alembic(command.downgrade, cfg, "p55a")
        try:
            await _run_alembic(command.upgrade, cfg, "p56a")

            engine = create_async_engine(_integration_db_url, echo=False)
            try:
                async with engine.connect() as conn:
                    result = await conn.execute(
                        text(
                            "SELECT pg_get_functiondef(oid)"
                            " FROM pg_proc WHERE proname = 'fn_notify_all_due'"
                        )
                    )
                    row = result.one_or_none()
                    assert row is not None, "fn_notify_all_due function not found"
                    assert "PENDING" in row[0], (
                        "fn_notify_all_due body does not reference PENDING:"
                        f" {row[0][:200]}"
                    )
            finally:
                await engine.dispose()
        finally:
            await _run_alembic(command.upgrade, cfg, "head")

    async def test_downgrade_restores_active_predicate(self, _integration_db_url):
        cfg = _alembic_cfg(_integration_db_url)
        # Start at p56a (or head), downgrade to p55a
        await _run_alembic(command.upgrade, cfg, "p56a")
        try:
            await _run_alembic(command.downgrade, cfg, "p55a")

            engine = create_async_engine(_integration_db_url, echo=False)
            try:
                async with engine.connect() as conn:
                    result = await conn.execute(
                        text(
                            "SELECT indexdef FROM pg_indexes"
                            " WHERE schemaname = 'sch_fbref_backend'"
                            "   AND indexname = 'ix_player_urls_due'"
                        )
                    )
                    row = result.one_or_none()
                    assert row is not None, (
                        "ix_player_urls_due not found after downgrade"
                    )
                    assert "PENDING" not in row[0], (
                        "Expected PENDING removed after downgrade,"
                        f" but found it: {row[0]}"
                    )
            finally:
                await engine.dispose()
        finally:
            await _run_alembic(command.upgrade, cfg, "head")

    async def test_upgrade_again_succeeds(self, _integration_db_url):
        cfg = _alembic_cfg(_integration_db_url)
        await _run_alembic(command.upgrade, cfg, "head")
        await _run_alembic(command.downgrade, cfg, "p55a")
        try:
            await _run_alembic(command.upgrade, cfg, "p56a")

            engine = create_async_engine(_integration_db_url, echo=False)
            try:
                async with engine.connect() as conn:
                    result = await conn.execute(
                        text(
                            "SELECT indexname, indexdef FROM pg_indexes"
                            " WHERE schemaname = 'sch_fbref_backend'"
                            "   AND indexname LIKE '%_due'"
                        )
                    )
                    rows = result.fetchall()
                    assert len(rows) == 5
                    for indexname, indexdef in rows:
                        assert "PENDING" in indexdef
            finally:
                await engine.dispose()
        finally:
            await _run_alembic(command.upgrade, cfg, "head")
