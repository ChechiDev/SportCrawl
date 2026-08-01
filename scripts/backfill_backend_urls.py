"""One-shot backfill script: populates sch_fbref_backend URL tables from existing data.

All inserts use ON CONFLICT DO NOTHING — safe to re-run without duplicating rows.

Usage:
    uv run python scripts/backfill_backend_urls.py
"""

from __future__ import annotations

import asyncio
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config.settings import Settings
from infrastructure.persistence.session import create_session_factory, get_session

# ---------------------------------------------------------------------------
# SQL statements
# ---------------------------------------------------------------------------

SQL_PLAYER_URLS = sa.text("""
    -- player_url dropped from tbl_players in p48a; URLs are now co-inserted by
    -- PlayerDiscoveryRepository at scrape time. This statement is a no-op placeholder.
    SELECT 1 WHERE false
""")

SQL_TEAM_URLS = sa.text("""
    INSERT INTO sch_fbref_backend.tbl_team_urls
        (fk_team, url_type, url, cadence_hours, priority, status, next_scrape_at)
    SELECT
        team_id,
        'squad',
        team_url,
        168,
        5,
        'PENDING',
        now()
    FROM sch_fbref_shared.tbl_teams
    WHERE team_url IS NOT NULL
    ON CONFLICT DO NOTHING
""")

SQL_COMPETITION_URLS = sa.text("""
    -- comp_url dropped from tbl_competition in p50a; URLs are now co-inserted by
    -- CompetitionsRepository at scrape time. This statement is a no-op placeholder.
    SELECT 1 WHERE false
""")

SQL_COUNTRY_URLS = sa.text("""
    -- country_url dropped from tbl_countries in p47a; URLs are now co-inserted by
    -- CountryRepository at scrape time. Only players_list URLs remain here.
    INSERT INTO sch_fbref_backend.tbl_country_urls
        (fk_country, url_type, url, cadence_hours, priority, status, next_scrape_at)
    SELECT
        country_id,
        'players_list',
        players_url,
        720,
        5,
        'PENDING',
        now()
    FROM sch_fbref_shared.tbl_countries
    WHERE players_url IS NOT NULL
    ON CONFLICT DO NOTHING
""")

SQL_COUNTRY_SQUAD_URLS = sa.text("""
    -- clubs_url dropped from tbl_country_squads in p49a; clubs URLs are now
    -- co-inserted by CountrySquadsRepository at scrape time.
    -- Only nat_team URLs remain here.
    INSERT INTO sch_fbref_backend.tbl_country_squad_urls
        (fk_country, url_type, url, cadence_hours, priority, status, next_scrape_at)
    SELECT
        fk_country,
        'nat_team_men',
        nat_team_men_url,
        720,
        5,
        'PENDING',
        now()
    FROM sch_fbref_shared.tbl_country_squads
    WHERE nat_team_men_url IS NOT NULL

    UNION ALL

    SELECT
        fk_country,
        'nat_team_women',
        nat_team_women_url,
        720,
        5,
        'PENDING',
        now()
    FROM sch_fbref_shared.tbl_country_squads
    WHERE nat_team_women_url IS NOT NULL

    ON CONFLICT DO NOTHING
""")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def _run_tasks(
    session_factory: async_sessionmaker[AsyncSession],
    tasks: list[tuple[str, sa.TextClause]],
) -> None:
    async with get_session(session_factory) as session:
        for table_name, stmt in tasks:
            cursor: CursorResult[Any] = (
                await session.execute(stmt)  # type: ignore[assignment]
            )
            await session.commit()
            print(f"✓ {table_name}: {cursor.rowcount} rows inserted")


async def sync_preflight() -> None:
    """Sync only tables available at preflight time (no scraping needed). Silent."""
    settings = Settings()  # type: ignore[call-arg]
    session_factory = create_session_factory(settings.db)
    async with get_session(session_factory) as session:
        for _, stmt in [
            ("tbl_competition_urls", SQL_COMPETITION_URLS),
            ("tbl_country_urls", SQL_COUNTRY_URLS),
            ("tbl_country_squad_urls", SQL_COUNTRY_SQUAD_URLS),
        ]:
            await session.execute(stmt)
            await session.commit()


async def main() -> None:
    """Full backfill — run manually after a complete scrape."""
    settings = Settings()  # type: ignore[call-arg]
    session_factory = create_session_factory(settings.db)
    await _run_tasks(session_factory, [
        ("tbl_player_urls", SQL_PLAYER_URLS),
        ("tbl_team_urls", SQL_TEAM_URLS),
        ("tbl_competition_urls", SQL_COMPETITION_URLS),
        ("tbl_country_urls", SQL_COUNTRY_URLS),
        ("tbl_country_squad_urls", SQL_COUNTRY_SQUAD_URLS),
    ])


if __name__ == "__main__":
    asyncio.run(main())
