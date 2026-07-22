"""CountryTeamsScraper — parses a FBRef country clubs page and persists results.

Concrete BaseScraper[TeamsPage] implementation.

Responsibilities:
  parse()   — pure HTML parsing; returns TeamsPage with no side effects.
  persist() — upserts parsed rows into tbl_teams via TeamsRepository.
  scrape()  — full pipeline: fetch → parse → persist → return page.
"""

from __future__ import annotations

import logging
import re
from typing import Literal

from bs4 import BeautifulSoup
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.exceptions.scraper import ParsingError
from domains.club.models import Team, TeamsPage
from infrastructure.persistence.repositories.teams import TeamsRepository
from ports.browser import ScrapingEngine
from ports.scraper import BaseScraper, ScraperConfig

logger = logging.getLogger(__name__)

_FBREF_BASE = "https://fbref.com"

# Extracts 8-char hex squad ID from /squads/{id}/... paths.
_SQUAD_ID_RE = re.compile(r"/squads/([0-9a-f]{8})/")


def _parse_year(season: str, take: Literal["lesser", "greater"]) -> int | None:
    """Parse a 'YYYY-YY' season string and return the lesser or greater year.

    Args:
        season: Season string in 'YYYY-YY' format (e.g. '2023-24').
        take: 'lesser' returns the first year; 'greater' returns the second year
              (interpreted as YYYY where only the last 2 digits differ).

    Returns:
        Integer year, or None if the format is invalid.
    """
    parts = season.split("-")
    if len(parts) != 2:
        return None
    try:
        if take == "lesser":
            return int(parts[0])
        else:
            return int(parts[1])
    except ValueError:
        return None


class CountryTeamsScraper(BaseScraper[TeamsPage]):
    """Scraper for a FBRef country clubs page (e.g. /en/country/clubs/ARG/...).

    Parses the clubs HTML table and extracts team/squad data including gender,
    competition, and active season range. Persistence is handled separately
    via persist() to respect SRP.
    """

    def __init__(
        self,
        engine: ScrapingEngine,
        settings: ScraperConfig,
        session_factory: async_sessionmaker[AsyncSession],
        fk_country: str,
    ) -> None:
        super().__init__(engine, settings)
        self._session_factory = session_factory
        self._fk_country = fk_country

    async def parse(self, html: str) -> TeamsPage:
        """Parse FBRef country clubs HTML into a TeamsPage.

        Pure parsing — no database calls.

        Args:
            html: Raw HTML source of the country clubs listing page.

        Returns:
            TeamsPage containing all successfully parsed team rows.

        Raises:
            ParsingError: if the clubs table is not found in the HTML.
        """
        soup = BeautifulSoup(html, "lxml")
        table = soup.find("table", {"id": "clubs"})
        if not table:
            raise ParsingError("clubs table not found")

        tbody = table.find("tbody")
        raw_rows = tbody.find_all("tr") if tbody else []

        teams: list[Team] = []

        for tr in raw_rows:
            # Skip embedded header rows (class="thead")
            row_classes = tr.get("class")
            if isinstance(row_classes, list) and "thead" in row_classes:
                continue

            # Team name and ID come from <th data-stat="team"><a ...>
            team_th = tr.find("th", {"data-stat": "team"})
            if not team_th:
                continue
            a_tag = team_th.find("a")
            if not a_tag:
                continue
            href = a_tag.get("href")
            if not isinstance(href, str):
                continue
            match = _SQUAD_ID_RE.search(href)
            if not match:
                continue

            team_id = match.group(1)
            team_name = a_tag.get_text(strip=True)
            team_url = _FBREF_BASE + href

            def _cell(stat: str) -> str:
                td = tr.find(["td", "th"], {"data-stat": stat})
                return td.get_text(strip=True) if td else ""

            gender_raw = _cell("gender")
            if gender_raw not in ("M", "F"):
                continue

            raw_comp = _cell("comp")
            comp_name: str | None = raw_comp if raw_comp else None

            team_from = _parse_year(_cell("min_season"), "lesser")
            team_to = _parse_year(_cell("max_season"), "greater")

            try:
                teams.append(
                    Team(
                        team_id=team_id,
                        team_name=team_name,
                        fk_country=self._fk_country,
                        gender_raw=gender_raw,
                        comp_name=comp_name,
                        team_from=team_from,
                        team_to=team_to,
                        team_url=team_url,
                    )
                )
            except ValidationError as exc:
                logger.warning("Skipping invalid team row: %s", exc)

        return TeamsPage(fk_country=self._fk_country, teams=teams)

    async def persist(self, page: TeamsPage, session: AsyncSession) -> int:
        """Upsert a parsed TeamsPage into the database.

        The caller owns the session transaction and must call session.commit().

        Args:
            page: A TeamsPage produced by parse().
            session: Open async SQLAlchemy session from the caller.

        Returns:
            Number of team rows processed.
        """
        repo = TeamsRepository(session)
        await repo.upsert(page.teams)
        return len(page.teams)

    async def scrape(self, url: str) -> TeamsPage:
        """Full pipeline: fetch HTML → parse → return page (no persist).

        Persistence is the caller's responsibility so that session ownership
        and commit timing remain with the script/worker layer.

        Args:
            url: The FBRef country clubs URL to fetch.

        Returns:
            TeamsPage with all parsed team rows.
        """
        return await self.fetch_and_parse(url)
