"""CountryScraper — parses the FBref countries page and persists results.

Concrete BaseScraper[CountryPage] implementation.

Responsibilities:
  parse()   — pure HTML parsing; returns CountryPage with no side effects.
  persist() — opens a session and upserts parsed rows via CountryRepository.
  scrape()  — full pipeline: fetch → parse → persist → return page.
"""

from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.exceptions.scraper import ParsingError
from domains.country.models import CountryPage, CountryRawData
from infrastructure.persistence.repositories.country import CountryRepository
from infrastructure.persistence.session import get_session
from ports.browser import ScrapingEngine
from ports.scraper import BaseScraper, ScraperConfig

logger = logging.getLogger(__name__)

_HREF_RE = re.compile(r"/en/country/([A-Za-z]{2,3})/", re.IGNORECASE)
_FLAG_CDN = "https://cdn.fbref.com/req/202301010/images/flags"


class CountryScraper(BaseScraper[CountryPage]):
    """Scraper for the FBref countries listing page.

    Parses the #countries HTML table and extracts country/flag/confederation data.
    Persistence is handled separately via persist() to respect SRP.
    """

    def __init__(
        self,
        engine: ScrapingEngine,
        settings: ScraperConfig,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        super().__init__(engine, settings)
        self._session_factory = session_factory

    async def parse(self, html: str) -> CountryPage:
        """Parse FBref countries HTML into a CountryPage.

        Pure parsing — no database calls.

        Args:
            html: Raw HTML source of the countries listing page.

        Returns:
            CountryPage containing all successfully parsed country rows.

        Raises:
            ParsingError: if the #countries table is not found in the HTML.
        """
        soup = BeautifulSoup(html, "lxml")
        table = soup.find("table", {"id": "countries"})
        if not table:
            raise ParsingError("countries table not found")

        tbody = table.find("tbody")
        rows = tbody.find_all("tr") if tbody else []

        country_list: list[CountryRawData] = []

        for row in rows:
            cells_by_stat = {
                cell.get("data-stat"): cell for cell in row.find_all(["th", "td"])
            }

            if "country" not in cells_by_stat:
                continue

            country_cell = cells_by_stat["country"]
            a_tag = country_cell.find("a")
            if not a_tag or not a_tag.get("href"):
                continue

            href = str(a_tag.get("href", ""))
            match = _HREF_RE.search(href)
            if not match:
                continue

            country_id = match.group(1).upper()
            country_name = country_cell.get_text(strip=True)
            country_url = href

            flag_td = cells_by_stat.get("flag")
            if not flag_td:
                continue
            flag_span = flag_td.find("span")
            flag_id = flag_span.get_text(strip=True) if flag_span else None
            if not flag_id:
                continue

            flag_url = f"{_FLAG_CDN}/{flag_id}.gif"

            governing = cells_by_stat.get("governing_body")
            confederation: str | None = None
            if governing:
                text = governing.get_text(strip=True)
                confederation = text if text else None

            try:
                country_data = CountryRawData(
                    country_id=country_id,
                    country_name=country_name,
                    country_url=country_url,
                    confederation=confederation,
                    flag_id=flag_id,
                    flag_url=flag_url,
                )
                country_list.append(country_data)
            except ValidationError:
                logger.debug(
                    "Skipping invalid country row",
                    extra={"country_id": country_id, "country_name": country_name},
                )
                continue

        return CountryPage(countries=country_list)

    async def persist(self, page: CountryPage) -> None:
        """Upsert a parsed CountryPage into the database.

        Opens its own session, upserts all rows via CountryRepository, and
        commits the transaction. The caller owns retry logic; this method
        delegates error handling to CountryRepository.

        Args:
            page: A CountryPage produced by parse().
        """
        async with get_session(self._session_factory) as session:
            repo = CountryRepository(session)
            await repo.upsert(page.countries)
            await session.commit()

    async def scrape(self, url: str) -> CountryPage:
        """Full pipeline: fetch HTML → parse → persist → return page.

        Overrides BaseScraper.fetch_and_parse() with a named scrape() entry
        point that chains parsing and persistence in a single call.

        Args:
            url: The FBref countries listing URL to fetch.

        Returns:
            CountryPage with all parsed and persisted country rows.
        """
        page = await self.fetch_and_parse(url)
        await self.persist(page)
        return page
