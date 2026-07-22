"""Country squads scraper — fetches and persists all country squad data from FBRef.

Usage:
    uv run python scripts/scrape_country_squads.py
"""

from __future__ import annotations

import asyncio
import logging

from config.settings import Settings
from infrastructure.browser.pydoll_engine import PydollEngine
from infrastructure.persistence.session import create_session_factory
from infrastructure.scraping.country_squads import CountrySquadsScraper

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

_SQUADS_URL = "https://fbref.com/en/squads/"


async def main() -> None:
    settings = Settings()  # type: ignore[call-arg]
    session_factory = create_session_factory(settings.db)
    async with PydollEngine(profile_dir=f"{settings.scraping.chrome_profile_dir}-country-squads") as engine:
        scraper = CountrySquadsScraper(engine, settings.scraping, session_factory)
        page = await scraper.scrape(_SQUADS_URL)
        print(f"Persisted {len(page.squads)} country squads.")


if __name__ == "__main__":
    asyncio.run(main())
