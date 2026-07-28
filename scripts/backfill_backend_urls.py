"""One-shot backfill script: populates sch_fbref_backend URL tables from existing domain data.

All inserts use ON CONFLICT DO NOTHING — safe to re-run without duplicating rows.

Usage:
    uv run python scripts/backfill_backend_urls.py
"""

from __future__ import annotations

import asyncio

import sqlalchemy as sa
from sqlalchemy.engine import CursorResult

from config.settings import Settings
from infrastructure.persistence.session import create_session_factory, get_session

# ---------------------------------------------------------------------------
# SQL statements
# ---------------------------------------------------------------------------

SQL_PLAYER_URLS = sa.text("""
    INSERT INTO sch_fbref_backend.tbl_player_urls
        (fk_player, url_type, url, cadence_hours, priority, status, next_scrape_at)
    SELECT
        player_id,
        'profile',
        player_url,
        168,
        5,
        'PENDING',
        now()
    FROM sch_fbref_shared.tbl_players
    WHERE player_url IS NOT NULL
    ON CONFLICT DO NOTHING
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
    INSERT INTO sch_fbref_backend.tbl_competition_urls
        (fk_comp, url_type, url, cadence_hours, priority, status, next_scrape_at)
    SELECT
        comp_id,
        'index',
        comp_url,
        720,
        3,
        'PENDING',
        now()
    FROM sch_fbref_shared.tbl_competition
    WHERE comp_url IS NOT NULL
    ON CONFLICT DO NOTHING
""")

SQL_COUNTRY_URLS = sa.text("""
    INSERT INTO sch_fbref_backend.tbl_country_urls
        (fk_country, url_type, url, cadence_hours, priority, status, next_scrape_at)
    SELECT
        country_id,
        'country',
        country_url,
        720,
        5,
        'PENDING',
        now()
    FROM sch_fbref_shared.tbl_countries
    WHERE country_url IS NOT NULL

    UNION ALL

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
    INSERT INTO sch_fbref_backend.tbl_country_squad_urls
        (fk_country, url_type, url, cadence_hours, priority, status, next_scrape_at)
    SELECT
        fk_country,
        'clubs',
        clubs_url,
        720,
        5,
        'PENDING',
        now()
    FROM sch_fbref_shared.tbl_country_squads
    WHERE clubs_url IS NOT NULL

    UNION ALL

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

async def main() -> None:
    settings = Settings()  # type: ignore[call-arg]
    session_factory = create_session_factory(settings.db)

    tasks: list[tuple[str, sa.TextClause]] = [
        ("tbl_player_urls", SQL_PLAYER_URLS),
        ("tbl_team_urls", SQL_TEAM_URLS),
        ("tbl_competition_urls", SQL_COMPETITION_URLS),
        ("tbl_country_urls", SQL_COUNTRY_URLS),
        ("tbl_country_squad_urls", SQL_COUNTRY_SQUAD_URLS),
    ]

    async with get_session(session_factory) as session:
        for table_name, stmt in tasks:
            cursor: CursorResult[sa.Any] = await session.execute(stmt)  # type: ignore[assignment]
            await session.commit()
            print(f"✓ {table_name}: {cursor.rowcount} rows inserted")


if __name__ == "__main__":
    asyncio.run(main())
