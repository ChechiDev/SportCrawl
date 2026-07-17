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
_EXPECTED_COUNT_RE = re.compile(r"(\d+)\s+Players", re.IGNORECASE)
_FBREF_BASE = "https://fbref.com"
_MIN_PARSE_RATIO = 0.90


class PlayerListScraper(BaseScraper[PlayerListPage]):
    """Scraper for FBRef country player-list pages.

    Parses the player table and extracts player_id, full_name,
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

    async def parse(self, html: str, country_id: str = "") -> PlayerListPage:
        """Parse FBRef country player-list HTML into a PlayerListPage.

        Pure parsing — no database calls, no instance state mutation.

        Args:
            html: Raw HTML source of the country player-list page.
            country_id: FBRef country code (e.g. "ESP"). Passed explicitly by
                fetch_and_parse(); callers such as tests may pass it directly.

        Returns:
            PlayerListPage containing all successfully parsed player rows.
        """
        if not country_id:
            raise ValueError("country_id must not be empty")
        soup = BeautifulSoup(html, "lxml")
        players: list[PlayerRawData] = []

        for p_tag in soup.find_all("p"):
            a_tag = p_tag.find("a")
            if not a_tag or not a_tag.get("href"):
                continue

            href = str(a_tag.get("href", ""))
            href_match = _PLAYER_HREF_RE.search(href)
            if not href_match:
                continue

            player_id = href_match.group(1).lower()
            full_name = a_tag.get_text(strip=True)

            # Build absolute player_url
            if href.startswith("http"):
                player_url = href
            else:
                player_url = f"{_FBREF_BASE}{href}"

            # Strip the player name from the full <p> text to isolate the date portion.
            # next_sibling is unreliable — FBRef often puts a bare newline there.
            tail = (
                p_tag.get_text(separator=" ")
                .replace(full_name, "", 1)
                .replace("\xa0", " ")
            )

            # Career dates from tail: "2004-2026 · FW,MF" or single year "2026 · FW"
            years_match = re.search(r"(\d{4})(?:-(\d{4}))?", tail)
            if years_match is None:
                logger.warning(
                    "No career dates found for player — tail=%r",
                    tail,
                    extra={"url": player_url},
                )
                continue

            career_start = int(years_match.group(1))
            end_str = years_match.group(2)
            career_end = int(end_str) if end_str else career_start

            players.append(
                PlayerRawData(
                    player_id=player_id,
                    full_name=full_name,
                    career_start=career_start,
                    career_end=career_end,
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
                page = await self.parse(html, country_id)

                # Validate against the "N Players" header FBRef injects.
                # If the page was partially rendered we get far fewer rows —
                # treat it as a transient load failure so the retry fires.
                expected_match = _EXPECTED_COUNT_RE.search(html)
                if expected_match:
                    expected = int(expected_match.group(1))
                    actual = len(page.players)
                    if actual < expected * _MIN_PARSE_RATIO:
                        raise PageLoadError(
                            f"Incomplete render: got {actual}/{expected} players"
                        )
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

    async def persist(self, page: PlayerListPage, country_id: str) -> int:
        """Bulk-enqueue a parsed PlayerListPage into the database.

        Opens its own session, inserts all rows via PlayerDiscoveryRepository,
        and commits the transaction. The caller owns retry logic.

        Args:
            page: A PlayerListPage produced by parse().
            country_id: FBRef country code to associate rows with.

        Returns:
            Number of player rows actually inserted (skips ON CONFLICT duplicates).
        """
        async with get_session(self._session_factory) as session:
            repo = PlayerDiscoveryRepository(session)
            inserted = await repo.bulk_enqueue(page.players, country_id)
            await session.commit()
        return inserted

    async def scrape(self, url: str) -> tuple[PlayerListPage, int]:
        """Full pipeline: fetch HTML → parse → persist → return page and inserted count.

        Args:
            url: The FBRef country player-list URL to fetch.

        Returns:
            Tuple of (PlayerListPage, inserted_count) where inserted_count is the
            number of new rows written to tbl_players (excludes ON CONFLICT skips).
        """
        page = await self.fetch_and_parse(url)
        inserted = await self.persist(page, page.country_id)
        return page, inserted
