"""CountryPlayersScraper — parses the FBref country-players index and persists results.

Concrete BaseScraper[CountryPlayersPage] implementation.

Responsibilities:
  parse()   — pure HTML parsing; returns CountryPlayersPage with no side effects.
  persist() — opens a session and updates players_url via CountryRepository.
  scrape()  — full pipeline: fetch → parse → persist → return page.
"""

from __future__ import annotations

import logging

from bs4 import BeautifulSoup
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.exceptions.scraper import ParsingError
from domains.country.models import CountryPlayersPage, CountryPlayersRawData
from infrastructure.persistence.repositories.country import CountryRepository
from infrastructure.persistence.session import get_session
from ports.browser import ScrapingEngine
from ports.scraper import BaseScraper, ScraperConfig

logger = logging.getLogger(__name__)

_FBREF_BASE = "https://fbref.com"


class CountryPlayersScraper(BaseScraper[CountryPlayersPage]):
    """Scraper for the FBref country-players index page.

    Parses ul.page_index and extracts country name + players_url for each entry.
    """

    def __init__(
        self,
        engine: ScrapingEngine,
        settings: ScraperConfig,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        super().__init__(engine, settings)
        self._session_factory = session_factory

    async def parse(self, html: str) -> CountryPlayersPage:
        """Parse FBref country-players index HTML into a CountryPlayersPage.

        Pure parsing — no database calls.

        Args:
            html: Raw HTML source of the country-players index page.

        Returns:
            CountryPlayersPage containing all successfully parsed entries.

        Raises:
            ParsingError: if ul.page_index is not found in the HTML.
        """
        soup = BeautifulSoup(html, "lxml")
        index = soup.find("ul", class_="page_index")
        if not index:
            raise ParsingError("ul.page_index not found")

        entries: list[CountryPlayersRawData] = []

        for li in index.find_all("li"):
            for div in li.find_all("div"):
                if "display:inline-block" not in (div.get("style") or ""):
                    continue
                a_tag = div.find("a")
                if not a_tag or not a_tag.get("href"):
                    continue

                country_name = a_tag.get_text(strip=True)
                players_url = f"{_FBREF_BASE}{a_tag['href']}"

                if country_name:
                    entries.append(
                        CountryPlayersRawData(
                            country_name=country_name,
                            players_url=players_url,
                        )
                    )

        return CountryPlayersPage(entries=entries)

    async def persist(self, page: CountryPlayersPage) -> None:
        """Update players_url on matched countries in the database.

        Opens its own session, updates all rows via CountryRepository, and
        commits the transaction.

        Args:
            page: A CountryPlayersPage produced by parse().
        """
        async with get_session(self._session_factory) as session:
            repo = CountryRepository(session)
            await repo.upsert_players_url(page.entries)
            await session.commit()

    async def scrape(self, url: str) -> CountryPlayersPage:
        """Full pipeline: fetch HTML → parse → persist → return page.

        Args:
            url: The FBref country-players index URL to fetch.

        Returns:
            CountryPlayersPage with all parsed and persisted entries.
        """
        page = await self.fetch_and_parse(url)
        await self.persist(page)
        return page
