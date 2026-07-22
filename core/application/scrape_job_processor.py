"""ScrapeJobProcessor — orchestrates parse → resolve FK → persist → mark done lifecycle.

Extracted from the _worker god coroutine in scripts/scrape_player_info.py.
Owns: parse HTML, resolve country/position FKs, persist player info, mark done/failed.
Does NOT own: browser engine lifetime, job claiming, or concurrency.
"""

from __future__ import annotations

import logging
from typing import Protocol

from sqlalchemy.orm import Mapped

from domains.player_info.models import PlayerInfoPage, PlayerInfoRawData

logger = logging.getLogger(__name__)


class _Job(Protocol):
    id: Mapped[int]


class _Scraper(Protocol):
    def parse(self, html: str) -> PlayerInfoPage: ...


class _QueueRepo(Protocol):
    async def mark_done(self, job_id: int) -> None: ...
    async def mark_failed(self, job_id: int, error: str) -> None: ...


class _PlayerInfoRepo(Protocol):
    async def upsert_player_info(
        self, raw: PlayerInfoRawData, pos_ids: tuple[int | None, int | None, int | None]
    ) -> None: ...
    async def upsert_photo(self, player_id: str, photo_url: str | None) -> None: ...
    async def upsert_position(self, position_code: str) -> int: ...


class ScrapeJobProcessor:
    """Processes a single scrape job: parse → FK resolution → persist → done/failed.

    Args:
        scraper: Object with a .parse(html) method returning PlayerInfoPage.
        queue_repo: Repository for marking jobs done/failed.
        player_info_repo: Repository for persisting player info.
        country_name_cache: Mapping of country_name → country_id for FK resolution.
        position_cache: Mutable mapping of position_code → position_id (in place).
        valid_countries: frozenset of valid country_id values for FK validation.
    """

    def __init__(
        self,
        scraper: _Scraper,
        queue_repo: _QueueRepo,
        player_info_repo: _PlayerInfoRepo,
        country_name_cache: dict[str, str],
        position_cache: dict[str, int],
        valid_countries: frozenset[str],
    ) -> None:
        self._scraper = scraper
        self._queue_repo = queue_repo
        self._player_info_repo = player_info_repo
        self._country_name_cache = country_name_cache
        self._position_cache = position_cache
        self._valid_countries = valid_countries

    async def process(
        self, job: _Job, html: str
    ) -> tuple[str, str | None] | None:
        """Parse, resolve FKs, persist, and mark the job done or failed.

        Args:
            job: The ScrapeQueue row being processed.
            html: Raw HTML fetched from the player profile URL.

        Returns:
            On success: (full_name, country_id) where country_id is
            fk_national_team if available, else fk_country_birth.
            On failure: None (error is logged and job is marked failed).

        Side effects:
            - Calls player_info_repo.upsert_player_info, upsert_photo, upsert_position
            - Calls queue_repo.mark_done on success
            - Calls queue_repo.mark_failed on any error
        """
        try:
            page = self._scraper.parse(html)

            if not page.players:
                raise RuntimeError("scraper returned empty page")

            raw: PlayerInfoRawData = page.players[0]

            # Resolve country name strings to FK country_id values
            if raw.country_birth_name is not None:
                raw.fk_country_birth = self._country_name_cache.get(
                    raw.country_birth_name
                )
                if raw.fk_country_birth is None:
                    logger.warning(
                        "Country birth name not found in cache: %r",
                        raw.country_birth_name,
                    )
            if raw.national_team_name is not None:
                raw.fk_national_team = self._country_name_cache.get(
                    raw.national_team_name
                )
            if raw.citizenship_name is not None:
                raw.fk_citizenship = self._country_name_cache.get(
                    raw.citizenship_name
                )
            if raw.youth_nat_team_name is not None:
                raw.fk_youth_nat_team = self._country_name_cache.get(
                    raw.youth_nat_team_name
                )

            # Validate resolved FK country IDs against the allowed set
            if raw.fk_country_birth not in self._valid_countries:
                raw.fk_country_birth = None
            if raw.fk_national_team not in self._valid_countries:
                raw.fk_national_team = None
            if raw.fk_citizenship not in self._valid_countries:
                raw.fk_citizenship = None
            if raw.fk_youth_nat_team not in self._valid_countries:
                raw.fk_youth_nat_team = None

            # Resolve position codes to surrogate IDs
            pos_ids = await self._resolve_positions(raw)

            await self._player_info_repo.upsert_player_info(raw, pos_ids)
            await self._player_info_repo.upsert_photo(raw.player_id, raw.photo_url)
            await self._queue_repo.mark_done(job.id)  # type: ignore[arg-type]

            country_id = raw.fk_national_team or raw.fk_country_birth
            return (raw.full_name or raw.player_id or "unknown", country_id)

        except Exception as exc:
            logger.error(
                "job %d failed: %s", job.id, exc, exc_info=False
            )
            try:
                await self._queue_repo.mark_failed(job.id, str(exc))  # type: ignore[arg-type]
            except Exception as mark_err:
                logger.error(
                    "Failed to mark job %d as failed: %s",
                    job.id,
                    mark_err,
                    exc_info=False,
                )
            return None

    async def _resolve_positions(
        self, raw: PlayerInfoRawData
    ) -> tuple[int | None, int | None, int | None]:
        pos_ids: list[int | None] = []
        for code in (raw.position_1, raw.position_2, raw.position_3):
            if code is not None:
                if code not in self._position_cache:
                    self._position_cache[code] = (
                        await self._player_info_repo.upsert_position(code)
                    )
                pos_ids.append(self._position_cache[code])
            else:
                pos_ids.append(None)
        return (pos_ids[0], pos_ids[1], pos_ids[2])
