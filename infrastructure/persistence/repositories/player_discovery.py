"""PlayerDiscoveryRepository — bulk-enqueues player discovery data.

Inserts Player skeletons, PlayerPosition rows, ScrapeQueue entries,
PlayerDiscoveryBatch upsert, and PlayerQueueRef links in FK-safe order.
Uses ON CONFLICT DO NOTHING throughout so repeated calls are idempotent.

NOT a BaseRepository subclass — coordinates five tables instead of one.
The caller owns the transaction; this repository never commits.
"""

from __future__ import annotations

import logging

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.repository import RepositoryError
from domains.player.models import PlayerRawData
from infrastructure.persistence.models.football.player_discovery_batch import (
    PlayerDiscoveryBatch,
)
from infrastructure.persistence.models.football.player_queue_ref import PlayerQueueRef
from infrastructure.persistence.models.scrape_queue import ScrapeQueue, ScrapeStatus
from infrastructure.persistence.models.shared.player import Player
from infrastructure.persistence.models.shared.player_position import PlayerPosition

logger = logging.getLogger(__name__)

_FBREF_DOMAIN = "fbref.com"


class PlayerDiscoveryRepository:
    """Persists player discovery data across five tables.

    Insert order per batch:
        1. tbl_players (Player) — ON CONFLICT(player_id) DO NOTHING
        2. tbl_player_positions (PlayerPosition) — ON CONFLICT DO NOTHING
        3. scrape_queue (ScrapeQueue) — ON CONFLICT(url) DO NOTHING
        4. player_discovery_batch — ON CONFLICT(country_id) DO UPDATE total_urls
        5. player_queue_ref (PlayerQueueRef) — after SELECT id FROM scrape_queue

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
            Number of player rows processed (len(rows)).

        Raises:
            RepositoryError: if any database operation fails.
        """
        if not rows:
            return 0

        try:
            # 1. Insert Player rows — ON CONFLICT(player_id) DO NOTHING
            player_values = [
                {
                    "player_id": r.player_id,
                    "display_name": r.display_name,
                    "full_name": r.full_name,
                    "career_start": r.career_start,
                    "career_end": r.career_end,
                    "fk_country_team": country_id,
                    "player_url": r.player_url,
                }
                for r in rows
            ]
            stmt_player = pg_insert(Player).values(player_values)
            stmt_player = stmt_player.on_conflict_do_nothing(
                index_elements=["player_id"]
            )
            await self._session.execute(stmt_player)

            # 2. Insert PlayerPosition rows — ON CONFLICT DO NOTHING
            position_values: list[dict[str, object]] = []
            for r in rows:
                for sort_order, pos_code in enumerate(r.positions):
                    position_values.append(
                        {
                            "fk_player": r.player_id,
                            "position_code": pos_code.strip(),
                            "sort_order": sort_order,
                        }
                    )
            if position_values:
                stmt_pos = pg_insert(PlayerPosition).values(position_values)
                stmt_pos = stmt_pos.on_conflict_do_nothing(
                    index_elements=["fk_player", "position_code"]
                )
                await self._session.execute(stmt_pos)

            # 3. Insert ScrapeQueue rows — ON CONFLICT(url) DO NOTHING
            sq_values = [
                {
                    "url": r.player_url,
                    "domain": _FBREF_DOMAIN,
                    "status": ScrapeStatus.PENDING,
                }
                for r in rows
            ]
            # urls derived from sq_values so ordering invariant is explicit:
            # urls[i] always matches sq_values[i]["url"]
            urls = [v["url"] for v in sq_values]
            stmt_sq = pg_insert(ScrapeQueue).values(sq_values)
            stmt_sq = stmt_sq.on_conflict_do_nothing(
                constraint="uq_scrape_queue_url"
            )
            await self._session.execute(stmt_sq)

            # 4. Upsert PlayerDiscoveryBatch — ON CONFLICT(country_id) DO UPDATE
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

            # 5. Resolve ScrapeQueue IDs, then insert PlayerQueueRef rows.
            #    pg_insert goes through Core (bypasses ORM UoW buffer), so rows are
            #    immediately visible to this SELECT within the same transaction.
            select_stmt = sa.select(ScrapeQueue.id).where(
                ScrapeQueue.url.in_(urls)
            )
            id_result = await self._session.execute(select_stmt)
            queue_ids: list[int] = list(id_result.scalars().all())

            if queue_ids:
                ref_values = [
                    {"queue_id": qid, "country_id": country_id}
                    for qid in queue_ids
                ]
                stmt_ref = pg_insert(PlayerQueueRef).values(ref_values)
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

        return len(rows)
