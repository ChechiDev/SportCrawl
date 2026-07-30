"""PlayerDiscoveryRepository — bulk-enqueues player discovery data.

Inserts Player rows, tbl_player_urls backend rows (for daemon scheduling),
and a PlayerDiscoveryBatch upsert. All operations are FK-safe and use
ON CONFLICT DO NOTHING / DO UPDATE throughout so repeated calls are idempotent.

NOT a BaseRepository subclass — coordinates multiple tables instead of one.
The caller owns the transaction; this repository never commits.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator
    from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.repository import RepositoryError
from domains.player.models import PlayerRawData
from infrastructure.persistence.models.infra.player_discovery_batch import (
    PlayerDiscoveryBatch,
)
from infrastructure.persistence.models.shared.player import Player

logger = logging.getLogger(__name__)

_CHUNK_SIZE = 500


def _chunked(lst: list[Any], size: int) -> Iterator[list[Any]]:
    for i in range(0, len(lst), size):
        yield lst[i : i + size]


class PlayerDiscoveryRepository:
    """Persists player discovery data.

    Insert order per batch:
        1. tbl_players (Player) — ON CONFLICT(player_id) DO NOTHING
        1b. tbl_player_urls (backend) — ON CONFLICT(fk_player, url_type) DO NOTHING
        2. player_discovery_batch — ON CONFLICT(country_id) DO UPDATE total_urls

    The caller owns the transaction and must call session.commit() after
    bulk_enqueue().
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def bulk_enqueue(self, rows: list[PlayerRawData], country_id: str) -> int:
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
            # Build a map of player_id → player_url for backend co-insert use.
            player_url_map: dict[str, str] = {r.player_id: r.player_url for r in rows}
            player_values = [
                {
                    "player_id": r.player_id,
                    "full_name": r.full_name,
                    "career_start": r.career_start,
                    "career_end": r.career_end,
                    "fk_country": country_id,
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

                # Co-insert backend scheduling rows — same transaction, best-effort.
                # player_url is no longer in tbl_players; use the Python-side value.
                try:
                    backend_values = [
                        {
                            "fk_player": c["player_id"],
                            "url": player_url_map[c["player_id"]],
                        }
                        for c in chunk
                        if c["player_id"] in player_url_map
                    ]
                    if backend_values:
                        await self._session.execute(
                            sa.text(
                                """
                                INSERT INTO sch_fbref_backend.tbl_player_urls
                                    (fk_player, url_type, url, cadence_hours, priority,
                                     status, next_scrape_at, created_at, updated_at, retry_count)
                                SELECT
                                    v.fk_player,
                                    'profile',
                                    v.url,
                                    168,
                                    5,
                                    'PENDING',
                                    now(), now(), now(), 0
                                FROM unnest(
                                    :player_ids ::text[],
                                    :urls ::text[]
                                ) AS v(fk_player, url)
                                ON CONFLICT (fk_player, url_type) DO NOTHING
                                """
                            ),
                            {
                                "player_ids": [v["fk_player"] for v in backend_values],
                                "urls": [v["url"] for v in backend_values],
                            },
                        )
                except Exception:
                    logger.warning(
                        "Backend co-insert failed for player chunk (country=%s); skipping",
                        country_id,
                        exc_info=True,
                    )

            # 2. PlayerDiscoveryBatch — single row, no chunking needed
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

        except SQLAlchemyError as exc:
            raise RepositoryError(
                "PlayerDiscoveryRepository.bulk_enqueue failed",
                operation="bulk_enqueue",
                cause=exc,
            ) from exc

        return inserted_count
