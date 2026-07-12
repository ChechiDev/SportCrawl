"""PlayerListScraper — parses FBRef country player-list pages and persists results.

Concrete BaseScraper[PlayerListPage] implementation.

Responsibilities:
  parse()          — pure HTML parsing; accepts country_id explicitly; no side effects.
  fetch_and_parse() — overrides BaseScraper; extracts country_id from URL and passes
                     it directly to parse(); adds per-request rate-limit sleep.
  persist()        — opens a session and bulk-enqueues rows via
                     PlayerDiscoveryRepository.
  scrape()         — full pipeline: fetch → parse → persist → return page.

Country ID is extracted from the FBRef URL pattern:
  /en/country/players/{CODE}/{Name}-Football
"""

from __future__ import annotations

import asyncio
import logging
import re
from random import uniform

from bs4 import BeautifulSoup
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from domains.player.models import PlayerListPage, PlayerRawData
from infrastructure.persistence.repositories.player_discovery import (
    PlayerDiscoveryRepository,
)
from infrastructure.persistence.session import get_session
from ports.browser import ScrapingEngine
from ports.scraper import BaseScraper, ScraperConfig

logger = logging.getLogger(__name__)

_PLAYER_HREF_RE = re.compile(r"/en/players/([a-z0-9]{8})/", re.IGNORECASE)
_COUNTRY_CODE_RE = re.compile(r"/en/country/players/([A-Za-z]{2,3})/", re.IGNORECASE)
_FBREF_BASE = "https://fbref.com"


class PlayerListScraper(BaseScraper[PlayerListPage]):
    """Scraper for FBRef country player-list pages.

    Parses the player table and extracts player_id, display_name, positions,
    career_start, and career_end for each row. Persistence is handled
    separately via persist() to respect SRP.

    The scraper extracts the country_id from the URL in fetch_and_parse() and
    passes it explicitly to parse(). Tests call parse(html, country_id=...) directly.
    """

    def __init__(
        self,
        engine: ScrapingEngine,
        settings: ScraperConfig,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        super().__init__(engine, settings)
        self._session_factory = session_factory

    async def parse(self, html: str, country_id: str = "") -> PlayerListPage:  # type: ignore[override]
        """Parse FBRef country player-list HTML into a PlayerListPage.

        Pure parsing — no database calls, no instance state mutation.

        Args:
            html: Raw HTML source of the country player-list page.
            country_id: FBRef country code (e.g. "ESP"). Passed explicitly by
                fetch_and_parse(); callers such as tests may pass it directly.

        Returns:
            PlayerListPage containing all successfully parsed player rows.
        """
        soup = BeautifulSoup(html, "lxml")

        # Find any table with a tbody (FBRef player list uses data-stat attributes)
        tbody = None
        for table in soup.find_all("table"):
            tbody = table.find("tbody")
            if tbody:
                break

        players: list[PlayerRawData] = []

        if not tbody:
            return PlayerListPage(country_id=country_id, players=players)

        for row in tbody.find_all("tr"):
            cells_by_stat = {
                cell.get("data-stat"): cell
                for cell in row.find_all(["th", "td"])
            }

            # Find the player anchor — could be in "player" stat or first td with <a>
            player_cell = cells_by_stat.get("player")
            if not player_cell:
                continue

            a_tag = player_cell.find("a")
            if not a_tag or not a_tag.get("href"):
                continue

            href = str(a_tag.get("href", ""))
            match = _PLAYER_HREF_RE.search(href)
            if not match:
                continue

            player_id = match.group(1).lower()
            display_name = a_tag.get_text(strip=True)

            # Build absolute player_url
            if href.startswith("http"):
                player_url = href
            else:
                player_url = f"{_FBREF_BASE}{href}"

            # Positions from data-stat="position" — e.g. "FW,MF"
            pos_cell = cells_by_stat.get("position")
            raw_pos = pos_cell.get_text(strip=True) if pos_cell else ""
            positions = (
                [p.strip() for p in raw_pos.split(",") if p.strip()]
                if raw_pos
                else []
            )

            # Career start from data-stat="career_start"
            start_cell = cells_by_stat.get("career_start")
            raw_start = start_cell.get_text(strip=True) if start_cell else ""
            try:
                career_start = int(raw_start)
            except (ValueError, TypeError):
                continue  # career_start is required; skip row if unparseable

            # Career end from data-stat="career_end" — empty means active
            end_cell = cells_by_stat.get("career_end")
            raw_end = end_cell.get_text(strip=True) if end_cell else ""
            career_end: int | None = None
            if raw_end:
                try:
                    career_end = int(raw_end)
                except (ValueError, TypeError):
                    # career_end is optional; None means currently active
                    career_end = None

            players.append(
                PlayerRawData(
                    player_id=player_id,
                    display_name=display_name,
                    full_name=None,
                    career_start=career_start,
                    career_end=career_end,
                    positions=positions,
                    player_url=player_url,
                )
            )

        return PlayerListPage(country_id=country_id, players=players)

    async def fetch_and_parse(self, url: str) -> PlayerListPage:
        """Fetch the player-list page, parse it, and apply a rate-limit delay.

        Extracts the country_id from the URL and passes it explicitly to parse()
        so no mutable side-effect is needed on the instance. The fetch loop
        mirrors BaseScraper.fetch_and_parse() and preserves identical retry
        and backoff semantics.

        Args:
            url: FBRef country player-list URL.

        Returns:
            PlayerListPage with country_id and parsed player rows.

        Raises:
            ScraperError: on HTTP or parse failure.
        """
        from core.exceptions.scraper import PageLoadError, RateLimitError, ScraperError

        # Derive country_id from URL path: /en/country/players/{CODE}/...
        country_match = _COUNTRY_CODE_RE.search(url)
        country_id = country_match.group(1).upper() if country_match else ""

        last_error: ScraperError | None = None

        for attempt in range(1, self._settings.max_retries + 1):
            try:
                logger.info("Fetching URL", extra={"url": url, "attempt": attempt})
                html = await self._engine.fetch(url)
                self._last_html = html
                # Pass country_id explicitly — no instance-state side-effect
                page = await self.parse(html, country_id)
                break
            except (PageLoadError, RateLimitError) as exc:
                last_error = exc
                if attempt < self._settings.max_retries:
                    backoff = min(
                        self._settings.base_delay * (2 ** (attempt - 1)),
                        self._settings.max_delay,
                    )
                    logger.warning(
                        "Fetch failed, retrying",
                        extra={"url": url, "attempt": attempt, "error": str(exc)},
                    )
                    await asyncio.sleep(backoff)
            except ScraperError:
                raise
        else:
            raise last_error or PageLoadError("fetch failed after retries", url=url)

        delay = uniform(
            self._settings.request_delay_min,
            self._settings.request_delay_max,
        )
        if delay > 0:
            logger.debug(
                "Rate-limit delay after player list fetch",
                extra={"delay": delay, "url": url},
            )
            await asyncio.sleep(delay)

        return page

    async def persist(self, page: PlayerListPage, country_id: str) -> None:
        """Bulk-enqueue a parsed PlayerListPage into the database.

        Opens its own session, inserts all rows via PlayerDiscoveryRepository,
        and commits the transaction. The caller owns retry logic.

        Args:
            page: A PlayerListPage produced by parse().
            country_id: FBRef country code to associate rows with.
        """
        async with get_session(self._session_factory) as session:
            repo = PlayerDiscoveryRepository(session)
            await repo.bulk_enqueue(page.players, country_id)
            await session.commit()

    async def scrape(self, url: str) -> PlayerListPage:
        """Full pipeline: fetch HTML → parse → persist → return page.

        Args:
            url: The FBRef country player-list URL to fetch.

        Returns:
            PlayerListPage with all parsed and persisted player rows.
        """
        page = await self.fetch_and_parse(url)
        await self.persist(page, page.country_id)
        return page
