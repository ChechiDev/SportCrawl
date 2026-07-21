"""Preflight checks for the sportcrawl pipeline.

Each check is async, connects to the DB independently, and returns a CheckResult.
This module MUST NOT import from infrastructure, domains, or ports.
"""
from __future__ import annotations

from typing import Literal

import asyncpg  # type: ignore[import-untyped]

from core.preflight.result import CheckResult

_REVISION_ORDER = [
    "134f2e68682a",
    "a3f8c1d29e5b",
    "5ab3b4f7d8a7",
    "p8a_lockdown_public",
    "p8b_create_sch_shared",
    "p8c_create_sch_football",
    "p10a_create_country_tables",
    "p10b_refactor_country_pk",
    "p10c_drop_public_schema",
    "p10d_add_fk_ondelete",
    "p11a",
    "p11b",
    "p11c",
    "p11d",
    "p11e",
    "p14a",
    "p14b",
    "p14c",
    "p14d",
    "p14e",
    "p14f",
    "p14g",
    "p14h",
    "p14i",
    "p14j",
    "p14k",
    "p14l",
    "p14m",
    "p15a",
]


def _revision_gte(current: str, minimum: str) -> bool:
    """Return True if current revision is >= minimum in the migration chain."""
    try:
        return _REVISION_ORDER.index(current) >= _REVISION_ORDER.index(minimum)
    except ValueError:
        return current == minimum


_COUNTRIES_TABLES = [
    "sch_infra.scrape_queue",
    "sch_shared.tbl_confederations",
    "sch_shared.tbl_gender",
    "sch_shared.tbl_countries",
]

_PLAYERS_TABLES = _COUNTRIES_TABLES + [
    "sch_shared.tbl_players",
    "sch_shared.tbl_player_positions",
    "sch_infra.player_discovery_batch",
    "sch_infra.player_queue_ref",
]

_PLAYER_INFO_TABLES = _PLAYERS_TABLES + [
    "sch_shared.tbl_player_info",
    "sch_shared.tbl_player_photo",
]

_PHASE_TABLES: dict[str, list[str]] = {
    "countries": _COUNTRIES_TABLES,
    "players": _PLAYERS_TABLES,
    "player_info": _PLAYER_INFO_TABLES,
}


async def check_db_reachable(dsn: str) -> CheckResult:
    try:
        conn = await asyncpg.connect(dsn, timeout=5)
        await conn.close()
        return CheckResult(
            name="DB reachable",
            passed=True,
            detail="Connected successfully.",
            fatal=True,
        )
    except Exception:
        return CheckResult(
            name="DB reachable",
            passed=False,
            detail="Cannot connect to PostgreSQL. Is Docker running?",
            fatal=True,
        )


async def check_alembic_initialized(dsn: str) -> CheckResult:
    conn = await asyncpg.connect(dsn, timeout=5)
    try:
        exists = await conn.fetchval(
            "SELECT to_regclass('sch_infra.alembic_version') IS NOT NULL AS exists"
        )
        if exists:
            return CheckResult(
                name="Alembic initialized",
                passed=True,
                detail="Migrations initialized successfully.",
                fatal=True,
            )
        return CheckResult(
            name="Alembic initialized",
            passed=False,
            detail="Fresh database detected — migrations have never run.",
            fatal=True,
        )
    finally:
        await conn.close()


async def check_alembic_revision(dsn: str, required_head: str) -> CheckResult:
    conn = await asyncpg.connect(dsn, timeout=5)
    try:
        current = await conn.fetchval(
            "SELECT version_num FROM sch_infra.alembic_version"
        )
        if _revision_gte(current, required_head):
            return CheckResult(
                name="Alembic revision",
                passed=True,
                detail="Database version up to date.",
                fatal=True,
            )
        return CheckResult(
            name="Alembic revision",
            passed=False,
            detail=(
                f"DB at revision {current}, minimum required: {required_head}. "
                f"Run: alembic upgrade head"
            ),
            fatal=True,
        )
    finally:
        await conn.close()


async def check_schemas_exist(dsn: str) -> CheckResult:
    conn = await asyncpg.connect(dsn, timeout=5)
    try:
        rows = await conn.fetch(
            "SELECT schema_name FROM information_schema.schemata "
            "WHERE schema_name IN ('sch_infra', 'sch_shared')"
        )
        if len(rows) >= 2:
            return CheckResult(
                name="Schemas exist",
                passed=True,
                detail="Database schemas verified.",
                fatal=True,
            )
        return CheckResult(
            name="Schemas exist",
            passed=False,
            detail="One or more required schemas are missing.",
            fatal=True,
        )
    finally:
        await conn.close()


async def check_tables_exist(
    dsn: str, phase: Literal["countries", "players", "player_info"]
) -> CheckResult:
    tables = _PHASE_TABLES[phase]
    conn = await asyncpg.connect(dsn, timeout=5)
    try:
        missing = []
        for table in tables:
            exists = await conn.fetchval(f"SELECT to_regclass('{table}')")
            if exists is None:
                missing.append(table)
        if not missing:
            return CheckResult(
                name="Tables exist",
                passed=True,
                detail="System tables ready.",
                fatal=True,
            )
        return CheckResult(
            name="Tables exist",
            passed=False,
            detail=f"Missing tables: {', '.join(missing)}",
            fatal=True,
        )
    finally:
        await conn.close()


async def check_seed_data(
    dsn: str, phase: Literal["players", "player_info"]
) -> CheckResult:
    conn = await asyncpg.connect(dsn, timeout=5)
    try:
        if phase == "players":
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM sch_shared.tbl_countries"
            )
            label = "countries"
        else:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM sch_shared.tbl_players"
            )
            label = "players"

        if count and count > 0:
            return CheckResult(
                name="Seed data",
                passed=True,
                detail=f"{count} {label} found.",
                fatal=True,
            )
        return CheckResult(
            name="Seed data",
            passed=False,
            detail=f"No {label} found. Seed data required for phase '{phase}'.",
            fatal=True,
        )
    finally:
        await conn.close()


async def check_clubs_data(dsn: str) -> CheckResult:
    conn = await asyncpg.connect(dsn, timeout=5)
    try:
        exists = await conn.fetchval(
            "SELECT to_regclass('sch_shared.tbl_clubs') IS NOT NULL"
        )
        if not exists:
            return CheckResult(
                name="Clubs data",
                passed=False,
                detail="Clubs not available yet — domain and scraping pending.",
                fatal=False,
            )
        count = await conn.fetchval("SELECT COUNT(*) FROM sch_shared.tbl_clubs")
        if count and count > 0:
            return CheckResult(
                name="Clubs data",
                passed=True,
                detail=f"{count} clubs loaded.",
                fatal=False,
            )
        return CheckResult(
            name="Clubs data",
            passed=False,
            detail="Clubs table exists but is empty.",
            fatal=False,
        )
    finally:
        await conn.close()


async def check_stale_queue(dsn: str) -> CheckResult:
    conn = await asyncpg.connect(dsn, timeout=5)
    try:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM sch_infra.scrape_queue "
            "WHERE status = 'IN_PROGRESS' AND locked_at < NOW() - INTERVAL '1 hour'"
        )
        if not count:
            count = 0
        if count == 0:
            return CheckResult(
                name="Stale queue",
                passed=True,
                detail="No stale jobs found.",
                fatal=False,
            )
        return CheckResult(
            name="Stale queue",
            passed=False,
            detail=f"{count} stale jobs found. Run with --recover-stale to reset them.",
            fatal=False,
        )
    finally:
        await conn.close()
