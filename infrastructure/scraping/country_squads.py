"""CountrySquadsScraper — parses the FBRef squads page and persists results.

Concrete BaseScraper[CountrySquadsPage] implementation.

Responsibilities:
  parse()   — pure HTML parsing; returns CountrySquadsPage with no side effects.
  persist() — opens a session and upserts parsed rows via CountrySquadsRepository.
  scrape()  — full pipeline: fetch → parse → persist → return page.
"""

from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.exceptions.scraper import ParsingError
from domains.club.models import CountrySquad, CountrySquadsPage
from infrastructure.persistence.repositories.country_squads import (
    CountrySquadsRepository,
)
from infrastructure.persistence.session import get_session
from ports.browser import ScrapingEngine
from ports.scraper import BaseScraper, ScraperConfig

logger = logging.getLogger(__name__)

_FBREF_BASE = "https://fbref.com"

# Extracts 3-letter country code from /en/country/clubs/ALB/... paths.
_CLUBS_HREF_RE = re.compile(r"/en/country/clubs/([A-Za-z]{3})/", re.IGNORECASE)

# Extracts 8-char hex squad id from /en/squads/{id}/... paths.
_SQUAD_ID_RE = re.compile(r"/en/squads/([a-z0-9]{8})/")

# FBRef link-text literals that distinguish men's from women's national teams.
# Fragile: tied to live HTML — update here if FBRef changes these strings.
_MEN_LINK_TEXT = "Men"
_WOMEN_LINK_TEXT = "Women"


class CountrySquadsScraper(BaseScraper[CountrySquadsPage]):
    """Scraper for the FBRef squads listing page (https://fbref.com/en/squads/).

    Parses the squads HTML table and extracts country/squad/flag/confederation data.
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

    async def parse(self, html: str) -> CountrySquadsPage:
        """Parse FBRef squads HTML into a CountrySquadsPage.

        Pure parsing — no database calls.

        Args:
            html: Raw HTML source of the squads listing page.

        Returns:
            CountrySquadsPage containing all successfully parsed squad rows.

        Raises:
            ParsingError: if the squads table is not found in the HTML.
        """
        soup = BeautifulSoup(html, "lxml")
        table = soup.find("table", {"id": "countries"})
        if not table:
            raise ParsingError("countries table not found")

        tbody = table.find("tbody")
        rows = tbody.find_all("tr") if tbody else []

        squad_list: list[CountrySquad] = []

        for row in rows:
            cells_by_stat = {
                cell.get("data-stat"): cell for cell in row.find_all(["th", "td"])
            }

            # Require club_count cell with an anchor — clubs_url + country code.
            club_count_cell = cells_by_stat.get("club_count")
            if not club_count_cell:
                continue

            club_anchor = club_count_cell.find("a")
            if not club_anchor or not club_anchor.get("href"):
                continue

            clubs_href = str(club_anchor.get("href", ""))
            code_match = _CLUBS_HREF_RE.search(clubs_href)
            if not code_match:
                logger.debug(
                    "Skipping row: cannot extract country code from href=%s", clubs_href
                )
                continue

            fk_country = code_match.group(1).upper()
            clubs_url = f"{_FBREF_BASE}{clubs_href}"

            # Flag: <span class="f-i f-al"> → extract 2-letter code after last "f-".
            fk_flag: str | None = None
            flag_cell = cells_by_stat.get("flag")
            if flag_cell:
                flag_span = flag_cell.find("span", class_="f-i")
                if flag_span:
                    class_attr: str | list[str] = flag_span.get("class") or []
                    classes: list[str] = (
                        class_attr if isinstance(class_attr, list) else [class_attr]
                    )
                    for cls in classes:
                        if cls.startswith("f-") and cls != "f-i":
                            fk_flag = cls[2:]  # strip leading "f-"
                            break

            # Confederation: governing_body cell text.
            confederation: str | None = None
            governing_cell = cells_by_stat.get("governing_body")
            if governing_cell:
                text = governing_cell.get_text(strip=True)
                confederation = text if text else None

            # National teams: up to two <a> tags, distinguished by link text.
            nat_team_men_url: str | None = None
            nat_team_women_url: str | None = None
            fbref_men_squad_id: str | None = None
            fbref_women_squad_id: str | None = None

            nat_cell = cells_by_stat.get("national_teams")
            if nat_cell:
                for anchor in nat_cell.find_all("a"):
                    link_text = anchor.get_text(strip=True)
                    href = str(anchor.get("href", ""))
                    full_url = f"{_FBREF_BASE}{href}"

                    squad_match = _SQUAD_ID_RE.search(href)
                    squad_id = squad_match.group(1) if squad_match else None
                    if not squad_id:
                        logger.debug(
                            "Could not extract squad id from href=%s (country=%s)",
                            href,
                            fk_country,
                        )

                    if link_text == _MEN_LINK_TEXT:
                        nat_team_men_url = full_url
                        fbref_men_squad_id = squad_id
                    elif link_text == _WOMEN_LINK_TEXT:
                        nat_team_women_url = full_url
                        fbref_women_squad_id = squad_id

            try:
                squad = CountrySquad(
                    fk_country=fk_country,
                    fk_flag=fk_flag,
                    confederation=confederation,
                    clubs_url=clubs_url,
                    nat_team_men_url=nat_team_men_url,
                    nat_team_women_url=nat_team_women_url,
                    fbref_men_squad_id=fbref_men_squad_id,
                    fbref_women_squad_id=fbref_women_squad_id,
                )
                squad_list.append(squad)
            except ValidationError:
                logger.debug(
                    "Skipping invalid squad row",
                    extra={"fk_country": fk_country},
                )
                continue

        return CountrySquadsPage(squads=squad_list)

    async def persist(self, page: CountrySquadsPage) -> None:
        """Upsert a parsed CountrySquadsPage into the database.

        Opens its own session, upserts all rows via CountrySquadsRepository, and
        commits the transaction. The caller owns retry logic; this method
        delegates error handling to CountrySquadsRepository.

        Args:
            page: A CountrySquadsPage produced by parse().
        """
        async with get_session(self._session_factory) as session:
            repo = CountrySquadsRepository(session)
            await repo.upsert(page.squads)
            await session.commit()

    async def scrape(self, url: str) -> CountrySquadsPage:
        """Full pipeline: fetch HTML → parse → persist → return page.

        Args:
            url: The FBRef squads listing URL to fetch.

        Returns:
            CountrySquadsPage with all parsed and persisted squad rows.
        """
        page = await self.fetch_and_parse(url)
        await self.persist(page)
        return page
