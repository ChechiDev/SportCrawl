"""PlayerPlayingTimeStatsRepository — upserts into tbl_player_playing_time_stats.

Tables managed:
    sch_fbref_football.tbl_player_playing_time_stats — main stats table

The caller owns the transaction; this repository never commits.
"""

from __future__ import annotations

import logging

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.repository import repo_error_context
from domains.player_stats.models import PlayerPlayingTimeStatsRawData
from infrastructure.persistence.models.football.player_playing_time_stats import (
    PlayerPlayingTimeStats,
)

logger = logging.getLogger(__name__)


class PlayerPlayingTimeStatsRepository:
    """Persists player playing time statistics into tbl_player_playing_time_stats.

    All methods are idempotent (ON CONFLICT ... DO UPDATE).
    The caller owns the transaction and must call session.commit().
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_bulk(self, rows: list[PlayerPlayingTimeStatsRawData]) -> int:
        """Upsert a list of playing time stats rows.

        For each row:
        1. Uses comp_id extracted by the scraper layer directly (no URL resolution).
        2. Upserts into tbl_player_playing_time_stats on PK conflict.

        Args:
            rows: Parsed rows from parse_player_playing_time_stats.

        Returns:
            Number of rows upserted.
        """
        if not rows:
            return 0

        count = 0
        for row in rows:
            async with repo_error_context("upsert_bulk", "upsert_bulk row failed"):
                await self._session.execute(
                    sa.text(
                        "INSERT INTO sch_fbref_shared.tbl_teams (team_id, team_url)"
                        " VALUES (:team_id, :team_url)"
                        " ON CONFLICT (team_id) DO NOTHING"
                    ),
                    {"team_id": row.fk_team, "team_url": row.team_url},
                )
                if row.comp_id is None:
                    continue
                row.fk_comp = row.comp_id

                values: dict[str, object] = {
                    "player_id": row.player_id,
                    "season": row.season,
                    "fk_team": row.fk_team,
                    "fk_country": row.fk_country,
                    "fk_comp": row.fk_comp,
                    "matches": row.matches,
                    "minutes": row.minutes,
                    "min_per_match": row.min_per_match,
                    "min_pct": row.min_pct,
                    "min_per_90": row.min_per_90,
                    "starts": row.starts,
                    "min_per_start": row.min_per_start,
                    "games_complete": row.games_complete,
                    "subs": row.subs,
                    "min_per_sub": row.min_per_sub,
                    "unused_sub": row.unused_sub,
                    "ppm": row.ppm,
                    "on_goals_for": row.on_goals_for,
                    "on_goals_against": row.on_goals_against,
                    "plus_minus": row.plus_minus,
                    "plus_minus_per90": row.plus_minus_per90,
                    "on_off": row.on_off,
                    "team_url": row.team_url,
                    "comp_url": None,
                    "match_url": row.match_url,
                }

                stmt = pg_insert(PlayerPlayingTimeStats).values(**values)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["player_id", "season", "fk_team", "fk_comp"],
                    set_={
                        "fk_country": stmt.excluded.fk_country,
                        "matches": stmt.excluded.matches,
                        "minutes": stmt.excluded.minutes,
                        "min_per_match": stmt.excluded.min_per_match,
                        "min_pct": stmt.excluded.min_pct,
                        "min_per_90": stmt.excluded.min_per_90,
                        "starts": stmt.excluded.starts,
                        "min_per_start": stmt.excluded.min_per_start,
                        "games_complete": stmt.excluded.games_complete,
                        "subs": stmt.excluded.subs,
                        "min_per_sub": stmt.excluded.min_per_sub,
                        "unused_sub": stmt.excluded.unused_sub,
                        "ppm": stmt.excluded.ppm,
                        "on_goals_for": stmt.excluded.on_goals_for,
                        "on_goals_against": stmt.excluded.on_goals_against,
                        "plus_minus": stmt.excluded.plus_minus,
                        "plus_minus_per90": stmt.excluded.plus_minus_per90,
                        "on_off": stmt.excluded.on_off,
                        "team_url": stmt.excluded.team_url,
                        "comp_url": stmt.excluded.comp_url,
                        "match_url": stmt.excluded.match_url,
                        "updated_at": sa.func.now(),
                    },
                )
                await self._session.execute(stmt)
                count += 1

        return count
