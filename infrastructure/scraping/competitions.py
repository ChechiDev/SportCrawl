"""CompetitionsScraper — parses the FBRef competitions page and persists results.

Concrete BaseScraper[CompetitionsPage] implementation.

Responsibilities:
  parse()   — pure HTML parsing; returns CompetitionsPage with no side effects.
  persist() — opens a session and upserts parsed rows via CompetitionsRepository.
  scrape()  — full pipeline: fetch → parse → persist → return page.
"""

from __future__ import annotations

import re as _re

from bs4 import BeautifulSoup, Tag
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from domains.competitions.models import CompetitionRawData, CompetitionsPage
from infrastructure.persistence.repositories.competitions import CompetitionsRepository
from infrastructure.persistence.session import get_session
from ports.browser import ScrapingEngine
from ports.scraper import BaseScraper, ScraperConfig

SECTION_MAP = {
    "Club International Cups": "Club International Cup",
    "National Team Competitions": "National Team Competition",
    "Domestic Leagues - 1st Tier": "Domestic League - 1st Tier",
    "Domestic Leagues - 2nd Tier": "Domestic League - 2nd Tier",
    "Domestic Leagues - 3rd Tier": "Domestic Leagues - 3rd Tier",
    "Domestic Leagues - 3rd Tier and Lower": "Domestic Leagues - 3rd Tier",
    "National Team Qualification": "National Team Qualification",
    "Domestic Cups": "Domestic Cup",
    "Domestic Youth Leagues": "Domestic Youth League",
}

_COMP_ID_RE = _re.compile(r"/en/comps/(\d+)/")
_COUNTRY_ID_RE = _re.compile(r"/en/country/(\w+)/")
_SEASON_RANGE_RE = _re.compile(r"^(\d{4})-(\d{4})$")
_SEASON_SINGLE_RE = _re.compile(r"^(\d{4})$")


def _text(tag: Tag | None) -> str:
    if tag is None:
        return ""
    return tag.get_text(strip=True)


def _parse_season(value: str, take_max: bool) -> int | None:
    value = value.strip()
    m = _SEASON_RANGE_RE.match(value)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        return max(a, b) if take_max else min(a, b)
    m = _SEASON_SINGLE_RE.match(value)
    if m:
        return int(m.group(1))
    return None


def parse_competitions(html: str) -> list[CompetitionRawData]:
    expanded = _re.sub(r"<!--(.*?)-->", r"\1", html, flags=_re.DOTALL)
    soup = BeautifulSoup(expanded, "lxml")
    results: list[CompetitionRawData] = []

    for h2 in soup.find_all("h2"):
        section_text = _text(h2)
        comp_type_name = SECTION_MAP.get(section_text)
        if comp_type_name is None:
            continue

        table = h2.find_next("table")
        if table is None:
            continue

        tbody = table.find("tbody")
        if tbody is None:
            continue

        for tr in tbody.find_all("tr"):
            link_tag = tr.find("a", href=_COMP_ID_RE)
            if link_tag is None:
                continue

            href = str(link_tag.get("href", ""))
            m = _COMP_ID_RE.search(href)
            if not m:
                continue

            comp_id = int(m.group(1))
            comp_name = _text(link_tag).upper()
            comp_url = href

            gender_td = tr.find("td", {"data-stat": "gender"})
            gender = _text(gender_td) or "M"

            conf_td = tr.find("td", {"data-stat": "governing_body"})
            conf_name: str | None = _text(conf_td) or None

            flag_id: str | None = None
            flag_td = tr.find("td", {"data-stat": "flag"})
            if flag_td:
                flag_span = flag_td.find("span")
                if flag_span:
                    raw = flag_span.get_text(strip=True)
                    flag_id = raw.upper() if raw else None

            country_id: str | None = None
            country_td = tr.find("td", {"data-stat": "country"})
            if country_td:
                country_link = country_td.find("a", href=_COUNTRY_ID_RE)
                if country_link:
                    cm = _COUNTRY_ID_RE.search(str(country_link.get("href", "")))
                    if cm:
                        country_id = cm.group(1)

            first_season_td = tr.find("td", {"data-stat": "minseason"})
            first_season = _parse_season(_text(first_season_td), take_max=False)

            last_season_td = tr.find("td", {"data-stat": "maxseason"})
            last_season = _parse_season(_text(last_season_td), take_max=True)

            results.append(
                CompetitionRawData(
                    comp_id=comp_id,
                    comp_name=comp_name,
                    comp_url=comp_url,
                    comp_type_name=comp_type_name,
                    gender=gender,
                    conf_name=conf_name,
                    flag_id=flag_id,
                    country_id=country_id,
                    first_season=first_season,
                    last_season=last_season,
                )
            )

    return results


class CompetitionsScraper(BaseScraper[CompetitionsPage]):
    """Scraper for the FBRef competitions listing page (https://fbref.com/en/comps/).

    Parses the competitions HTML tables and extracts competition metadata.
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

    async def parse(self, html: str) -> CompetitionsPage:
        return CompetitionsPage(competitions=parse_competitions(html))

    async def persist(self, page: CompetitionsPage) -> None:
        async with get_session(self._session_factory) as session:
            repo = CompetitionsRepository(session)
            await repo.upsert_bulk(page.competitions)
            await session.commit()

    async def scrape(self, url: str) -> CompetitionsPage:
        page = await self.fetch_and_parse(url)
        await self.persist(page)
        return page
