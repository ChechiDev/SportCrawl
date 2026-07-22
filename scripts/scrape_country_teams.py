"""Country teams scraper — fetches and persists team data for each country from FBRef.

Iterates over all rows in tbl_country_squads that have a clubs_url, then scrapes
the teams/clubs listing page for each country and upserts results into tbl_teams.

Usage:
    uv run python scripts/scrape_country_teams.py
"""

from __future__ import annotations

import asyncio
import logging

import sqlalchemy as sa
from rich.console import Console

from config.settings import Settings
from infrastructure.browser.pydoll_engine import PydollEngine
from infrastructure.persistence.models.shared.country_squads import CountrySquads
from infrastructure.persistence.session import create_session_factory, get_session
from infrastructure.scraping.country_teams import CountryTeamsScraper

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")


async def main() -> None:
    settings = Settings()  # type: ignore[call-arg]
    session_factory = create_session_factory(settings.db)

    # Load all country squads with a clubs_url
    async with get_session(session_factory) as session:
        result = await session.execute(
            sa.select(CountrySquads.fk_country, CountrySquads.clubs_url).where(
                CountrySquads.clubs_url.isnot(None)
            )
        )
        rows = result.fetchall()

    console = Console()
    console.print(f"[bold]Scraping teams for {len(rows)} countries...[/bold]")

    for fk_country, clubs_url in rows:
        engine = PydollEngine(
            profile_dir=(
                f"{settings.scraping.chrome_profile_dir}-teams-{fk_country}"
            ),
            name=f"Teams-{fk_country}",
        )
        scraper = CountryTeamsScraper(
            engine=engine,
            settings=settings.scraping,
            session_factory=session_factory,
            fk_country=fk_country,
        )
        async with engine:
            page = await scraper.scrape(clubs_url)
            async with get_session(session_factory) as db_session:
                count = await scraper.persist(page, db_session)
                await db_session.commit()
        console.print(f"  {fk_country}: {count} teams")


if __name__ == "__main__":
    asyncio.run(main())
