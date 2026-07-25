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

import sqlalchemy as sa
from sqlalchemy import func, select
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
            stmt_insert = pg_insert(PlayerPosition).values(position_code=position_code)
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
    ) -> None:
        """Insert or update a tbl_player_info row.

        Uses ON CONFLICT(player_id) DO UPDATE to overwrite all fields on repeat
        runs, so re-scraping a profile is idempotent.

        FK country IDs must already be validated by the caller (application layer).

        Args:
            raw: Parsed player info from PlayerInfoScraper. FK country fields must
                already be validated or set to None before calling.
            pos_ids: Tuple of (fk_ply_pos_1, fk_ply_pos_2, fk_ply_pos_3) surrogate ids.

        Raises:
            RepositoryError: if the upsert fails.
        """
        async with repo_error_context(
            "upsert_player_info", "upsert_player_info failed"
        ):
            fk1, fk2, fk3 = pos_ids

            values: dict[str, object] = {
                "player_id": raw.player_id,
                "fk_country_birth": raw.fk_country_birth,
                "fk_national_team": raw.fk_national_team,
                "fk_youth_nat_team": raw.fk_youth_nat_team,
                "fk_city": raw.fk_city,
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
                "club_name": raw.club_name,
                "club_url": raw.club_url,
            }
            stmt = pg_insert(PlayerInfo).values(**values)
            stmt = stmt.on_conflict_do_update(
                index_elements=["player_id"],
                set_={
                    "fk_country_birth": stmt.excluded.fk_country_birth,
                    "fk_national_team": stmt.excluded.fk_national_team,
                    "fk_youth_nat_team": stmt.excluded.fk_youth_nat_team,
                    "fk_city": stmt.excluded.fk_city,
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
                    "club_name": stmt.excluded.club_name,
                    "club_url": stmt.excluded.club_url,
                    "updated_at": func.now(),
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

    async def upsert_city(self, city_name: str) -> int:
        """Insert city if not exists, return city_id.

        Args:
            city_name: Free-text birth city name.

        Returns:
            The city_id (existing or newly created).

        Raises:
            RepositoryError: if any database operation fails.
        """
        async with repo_error_context("upsert_city", "upsert_city failed"):
            await self._session.execute(
                sa.text(
                    "INSERT INTO sch_shared.tbl_cities (city_name)"
                    " VALUES (:city_name)"
                    " ON CONFLICT (city_name) DO NOTHING"
                ),
                {"city_name": city_name},
            )
            result = await self._session.execute(
                sa.text(
                    "SELECT city_id FROM sch_shared.tbl_cities WHERE city_name = :city_name"
                ),
                {"city_name": city_name},
            )
            city_id = result.scalar()
            if city_id is None:
                raise ValueError(f"City not found after upsert: {city_name!r}")
            return int(city_id)

    async def upsert_citizenship(self, player_id: str, fk_country: str) -> None:
        """Insert a citizenship row, ignoring if the pair already exists.

        Args:
            player_id: FBRef slug (FK → tbl_players.player_id).
            fk_country: country_id FK (FK → tbl_countries.country_id).

        Raises:
            RepositoryError: if the insert fails.
        """
        async with repo_error_context("upsert_citizenship", "upsert_citizenship failed"):
            stmt = sa.text(
                "INSERT INTO sch_shared.tbl_player_citizenship (player_id, fk_country)"
                " VALUES (:player_id, :fk_country)"
                " ON CONFLICT (player_id, fk_country) DO NOTHING"
            )
            await self._session.execute(
                stmt, {"player_id": player_id, "fk_country": fk_country}
            )
