"""Country scraper — fetches and persists all countries from FBref.

Usage:
    uv run python scripts/scrape_countries.py
"""

from __future__ import annotations

import asyncio
import logging

from config.settings import Settings
from infrastructure.browser.pydoll_engine import PydollEngine
from infrastructure.persistence.session import create_session_factory
from infrastructure.scraping.countries import CountryScraper

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

_COUNTRIES_URL = "https://fbref.com/en/countries/"


async def main() -> None:
    settings = Settings()  # type: ignore[call-arg]
    session_factory = create_session_factory(settings.db)
    async with PydollEngine() as engine:
        scraper = CountryScraper(engine, settings.scraping, session_factory)
        page = await scraper.scrape(_COUNTRIES_URL)
        logging.info("Persisted %d countries.", len(page.countries))


if __name__ == "__main__":
    asyncio.run(main())
