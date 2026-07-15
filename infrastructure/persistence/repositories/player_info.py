"""PlayerInfoRepository — upserts player biographical data across three tables.

Tables managed:
    tbl_player_info     — biographical + contract fields per player
    tbl_player_positions — position lookup (upsert returns surrogate id)
    tbl_player_photo    — one photo URL per player (skipped when absent)

NOT a BaseRepository subclass — coordinates three tables directly.
The caller owns the transaction; this repository never commits.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.repository import RepositoryError, repo_error_context
from domains.player_info.models import PlayerInfoRawData
from infrastructure.persistence.models.shared.player_info import PlayerInfo
from infrastructure.persistence.models.shared.player_photo import PlayerPhoto
from infrastructure.persistence.models.shared.player_position import PlayerPosition

logger = logging.getLogger(__name__)


class PlayerInfoRepository:
    """Persists player info data across tbl_player_info, tbl_player_positions,
    and tbl_player_photo.

    All methods are idempotent (ON CONFLICT ... DO UPDATE / DO NOTHING).
    The caller owns the transaction and must call session.commit().
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_position(self, position_code: str) -> int:
        """Ensure a position_code row exists and return its position_id.

        Issues INSERT ON CONFLICT DO NOTHING, then SELECT to retrieve the id.
        Both steps run in the same session (same transaction context as the caller).

        Args:
            position_code: Short position string (e.g. "FW", "MF").

        Returns:
            The position_id (existing or newly created).

        Raises:
            RepositoryError: if any database operation fails or the row is not found
                after insert (should not happen in normal operation).
        """
        async with repo_error_context("upsert_position", "upsert_position failed"):
            stmt_insert = pg_insert(PlayerPosition).values(
                position_code=position_code
            )
            stmt_insert = stmt_insert.on_conflict_do_nothing(
                index_elements=["position_code"]
            )
            await self._session.execute(stmt_insert)

            stmt_select = select(PlayerPosition.position_id).where(
                PlayerPosition.position_code == position_code
            )
            result = await self._session.execute(stmt_select)
            position_id = result.scalar_one_or_none()
            if position_id is None:
                raise RepositoryError(
                    f"upsert_position: position_code '{position_code}' "
                    "not found after insert",
                    operation="upsert_position",
                )
            return int(position_id)

    async def upsert_player_info(
        self,
        raw: PlayerInfoRawData,
        pos_ids: tuple[int | None, int | None, int | None],
        valid_countries: frozenset[str] = frozenset(),
    ) -> None:
        """Insert or update a tbl_player_info row.

        Uses ON CONFLICT(player_id) DO UPDATE to overwrite all fields on repeat
        runs, so re-scraping a profile is idempotent.

        Args:
            raw: Parsed player info from PlayerInfoScraper.
            pos_ids: Tuple of (fk_ply_pos_1, fk_ply_pos_2, fk_ply_pos_3) surrogate ids.

        Raises:
            RepositoryError: if the upsert fails.
        """
        async with repo_error_context(
            "upsert_player_info", "upsert_player_info failed"
        ):
            fk1, fk2, fk3 = pos_ids

            fk_country_birth = (
                raw.fk_country_birth
                if raw.fk_country_birth in valid_countries
                else None
            )

            values: dict[str, object] = {
                "player_id": raw.player_id,
                "fk_country_birth": fk_country_birth,
                "city_name": raw.city_name,
                "player_born": raw.player_born,
                "player_height": raw.player_height,
                "player_weight": raw.player_weight,
                "fk_ply_pos_1": fk1,
                "fk_ply_pos_2": fk2,
                "fk_ply_pos_3": fk3,
                "player_foot": raw.player_foot,
                "player_wages": raw.player_wages,
                "player_expires": raw.player_expires,
                "player_info_url": raw.player_info_url,
            }
            stmt = pg_insert(PlayerInfo).values(**values)
            stmt = stmt.on_conflict_do_update(
                index_elements=["player_id"],
                set_={
                    "fk_country_birth": stmt.excluded.fk_country_birth,
                    "city_name": stmt.excluded.city_name,
                    "player_born": stmt.excluded.player_born,
                    "player_height": stmt.excluded.player_height,
                    "player_weight": stmt.excluded.player_weight,
                    "fk_ply_pos_1": stmt.excluded.fk_ply_pos_1,
                    "fk_ply_pos_2": stmt.excluded.fk_ply_pos_2,
                    "fk_ply_pos_3": stmt.excluded.fk_ply_pos_3,
                    "player_foot": stmt.excluded.player_foot,
                    "player_wages": stmt.excluded.player_wages,
                    "player_expires": stmt.excluded.player_expires,
                    "player_info_url": stmt.excluded.player_info_url,
                },
            )
            await self._session.execute(stmt)

    async def upsert_photo(self, player_id: str, photo_url: str | None) -> None:
        """Insert or update the player photo URL.

        When photo_url is None, this method returns immediately without any
        database call — missing photos are not persisted.

        Args:
            player_id: FBRef slug (FK → tbl_players.player_id).
            photo_url: Absolute URL to the player photo, or None.

        Raises:
            RepositoryError: if the insert fails.
        """
        if photo_url is None:
            return

        async with repo_error_context("upsert_photo", "upsert_photo failed"):
            stmt = pg_insert(PlayerPhoto).values(
                player_id=player_id,
                player_photo_url=photo_url,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["player_id"],
                set_={"player_photo_url": stmt.excluded.player_photo_url},
            )
            await self._session.execute(stmt)
