"""PlayerDiscoveryRepository — bulk-enqueues player discovery data.

Inserts Player rows, then ScrapeQueue entries, PlayerDiscoveryBatch upsert,
and PlayerQueueRef links. All operations are FK-safe and use ON CONFLICT
DO NOTHING throughout so repeated calls are idempotent.

NOT a BaseRepository subclass — coordinates four tables instead of one.
The caller owns the transaction; this repository never commits.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator
    from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.repository import RepositoryError
from domains.player.models import PlayerRawData
from infrastructure.persistence.models.infra.player_discovery_batch import (
    PlayerDiscoveryBatch,
)
from infrastructure.persistence.models.infra.player_queue_ref import PlayerQueueRef
from infrastructure.persistence.models.scrape_queue import ScrapeQueue, ScrapeStatus
from infrastructure.persistence.models.shared.player import Player

logger = logging.getLogger(__name__)

_FBREF_DOMAIN = "fbref.com"
_CHUNK_SIZE = 500


def _chunked(lst: list[Any], size: int) -> Iterator[list[Any]]:
    for i in range(0, len(lst), size):
        yield lst[i : i + size]


class PlayerDiscoveryRepository:
    """Persists player discovery data across four tables.

    Insert order per batch:
        1. tbl_players (Player) — ON CONFLICT(player_id) DO NOTHING
        2. scrape_queue (ScrapeQueue) — ON CONFLICT(url) DO UPDATE (no-op) RETURNING id
        3. player_discovery_batch — ON CONFLICT(country_id) DO UPDATE total_urls
        4. player_queue_ref (PlayerQueueRef) — IDs from step 2 RETURNING clause

    The caller owns the transaction and must call session.commit() after
    bulk_enqueue().
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def bulk_enqueue(
        self, rows: list[PlayerRawData], country_id: str
    ) -> int:
        """Bulk-insert player discovery data for a single country page.

        Args:
            rows: Parsed player rows from PlayerListScraper.
            country_id: FBRef country code (e.g. "ESP").

        Returns:
            Number of player rows processed.

        Raises:
            RepositoryError: if any database operation fails.
        """
        if not rows:
            return 0

        try:
            # 1. Player rows — chunked to stay under asyncpg 32 767-param limit
            player_values = [
                {
                    "player_id": r.player_id,
                    "full_name": r.full_name,
                    "career_start": r.career_start,
                    "career_end": r.career_end,
                    "fk_country": country_id,
                    "player_url": r.player_url,
                }
                for r in rows
            ]

            inserted_count = 0
            for chunk in _chunked(player_values, _CHUNK_SIZE):
                stmt_player = pg_insert(Player).values(chunk)
                stmt_player = stmt_player.on_conflict_do_nothing(
                    index_elements=["player_id"]
                )
                raw = await self._session.execute(stmt_player)
                inserted_count += raw.rowcount  # type: ignore[attr-defined]

            # 2. ScrapeQueue upsert with RETURNING — collect IDs across all chunks
            sq_values = [
                {
                    "url": r.player_url,
                    "domain": _FBREF_DOMAIN,
                    "status": ScrapeStatus.PENDING,
                    "job_type": "player_discovery",
                }
                for r in rows
            ]
            queue_ids: list[int] = []
            for chunk in _chunked(sq_values, _CHUNK_SIZE):
                stmt_sq = pg_insert(ScrapeQueue).values(chunk)
                stmt_sq = stmt_sq.on_conflict_do_update(
                    index_elements=["url", "job_type"],
                    # no-op update — forces RETURNING to include conflicting rows too
                    set_={"url": pg_insert(ScrapeQueue).excluded.url},
                )
                stmt_sq_ret = stmt_sq.returning(ScrapeQueue.id)
                sq_result = await self._session.execute(stmt_sq_ret)
                queue_ids.extend(sq_result.scalars().all())

            # 3. PlayerDiscoveryBatch — single row, no chunking needed
            stmt_batch = pg_insert(PlayerDiscoveryBatch).values(
                country_id=country_id,
                total_urls=len(rows),
            )
            stmt_batch = stmt_batch.on_conflict_do_update(
                index_elements=["country_id"],
                # last-write-wins: FBRef returns all players in one page per country
                set_={"total_urls": len(rows)},
            )
            await self._session.execute(stmt_batch)

            # 4. PlayerQueueRef — chunked
            if queue_ids:
                ref_values = [
                    {"queue_id": qid, "country_id": country_id}
                    for qid in queue_ids
                ]
                for chunk in _chunked(ref_values, _CHUNK_SIZE):
                    stmt_ref = pg_insert(PlayerQueueRef).values(chunk)
                    stmt_ref = stmt_ref.on_conflict_do_nothing(
                        index_elements=["queue_id"]
                    )
                    await self._session.execute(stmt_ref)

        except SQLAlchemyError as exc:
            raise RepositoryError(
                "PlayerDiscoveryRepository.bulk_enqueue failed",
                operation="bulk_enqueue",
                cause=exc,
            ) from exc

        return inserted_count
