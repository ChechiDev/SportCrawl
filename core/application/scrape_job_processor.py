"""ScrapeJobProcessor — orchestrates parse → resolve FK → persist → mark done lifecycle.

Extracted from the _worker god coroutine in scripts/scrape_player_info.py.
Owns: parse HTML, resolve country/position FKs, persist player info, mark job done/failed.
Does NOT own: browser engine lifetime, job claiming, or concurrency.
"""

from __future__ import annotations

import logging

from domains.player_info.models import PlayerInfoRawData
from infrastructure.persistence.models.scrape_queue import ScrapeQueue

logger = logging.getLogger(__name__)


class ScrapeJobProcessor:
    """Processes a single scrape job: parse → FK resolution → persist → mark done/failed.

    Args:
        scraper: Object with a .parse(html) method returning PlayerInfoPage.
        queue_repo: Repository for marking jobs done/failed (mark_done, mark_failed).
        player_info_repo: Repository for persisting player info (upsert_player_info,
            upsert_photo, upsert_position).
        country_name_cache: Mapping of country_name → country_id for FK resolution.
        position_cache: Mutable mapping of position_code → position_id (updated in place).
        valid_countries: frozenset of valid country_id values for FK validation.
    """

    def __init__(
        self,
        scraper: object,
        queue_repo: object,
        player_info_repo: object,
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

    async def process(self, job: ScrapeQueue, html: str) -> None:
        """Parse, resolve FKs, persist, and mark the job done or failed.

        Args:
            job: The ScrapeQueue row being processed.
            html: Raw HTML fetched from the player profile URL.

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

            # Resolve position codes to surrogate IDs
            pos_ids = await self._resolve_positions(raw)

            await self._player_info_repo.upsert_player_info(
                raw, pos_ids, self._valid_countries
            )
            await self._player_info_repo.upsert_photo(raw.player_id, raw.photo_url)
            await self._queue_repo.mark_done(job.id)

        except Exception as exc:
            logger.error(
                "job %d failed: %s", job.id, exc, exc_info=True
            )
            await self._queue_repo.mark_failed(job.id, str(exc))

    async def _resolve_positions(
        self, raw: PlayerInfoRawData
    ) -> tuple[int | None, int | None, int | None]:
        pos_ids: list[int | None] = []
        for code in (raw.position_1, raw.position_2, raw.position_3):
            if code is not None:
                if code not in self._position_cache:
                    self._position_cache[code] = await self._player_info_repo.upsert_position(code)
                pos_ids.append(self._position_cache[code])
            else:
                pos_ids.append(None)
        return (pos_ids[0], pos_ids[1], pos_ids[2])
