"""PlayerShootingStatsRepository — upserts into tbl_player_shooting_stats.

Tables managed:
    sch_shared.tbl_competition  — comp_name upsert (get or create comp_id)
    sch_football.tbl_player_shooting_stats — main stats table

The caller owns the transaction; this repository never commits.
"""

from __future__ import annotations

import logging

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.repository import repo_error_context
from domains.player_stats.models import PlayerShootingStatsRawData
from infrastructure.persistence.models.football.player_shooting_stats import (
    PlayerShootingStats,
)
from infrastructure.persistence.models.shared.competition import Competition

logger = logging.getLogger(__name__)


class PlayerShootingStatsRepository:
    """Persists player shooting statistics into tbl_player_shooting_stats.

    All methods are idempotent (ON CONFLICT ... DO UPDATE).
    The caller owns the transaction and must call session.commit().
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _resolve_comp_id(self, comp_name: str) -> int:
        async with repo_error_context("resolve_comp_id", "resolve_comp_id failed"):
            stmt = pg_insert(Competition).values(comp_name=comp_name)
            stmt = stmt.on_conflict_do_nothing(
                constraint="uq_tbl_competition_comp_name"
            )
            await self._session.execute(stmt)

            result = await self._session.execute(
                sa.select(Competition.comp_id).where(
                    Competition.comp_name == comp_name
                )
            )
            comp_id = result.scalar_one()
            return int(comp_id)

    async def upsert_bulk(self, rows: list[PlayerShootingStatsRawData]) -> int:
        """Upsert a list of shooting stats rows.

        For each row:
        1. Resolves fk_comp via comp_name upsert into tbl_competition.
        2. Upserts into tbl_player_shooting_stats on PK conflict.

        Args:
            rows: Parsed rows from parse_player_shooting_stats.

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
                        "INSERT INTO sch_shared.tbl_teams (team_id, team_url)"
                        " VALUES (:team_id, :team_url)"
                        " ON CONFLICT (team_id) DO NOTHING"
                    ),
                    {"team_id": row.fk_team, "team_url": row.team_url},
                )
                comp_id = await self._resolve_comp_id(row.comp_name or "Unknown")
                row.fk_comp = comp_id

                values: dict[str, object] = {
                    "player_id": row.player_id,
                    "season": row.season,
                    "fk_team": row.fk_team,
                    "fk_country": row.fk_country,
                    "fk_comp": row.fk_comp,
                    "min_per_90": row.min_per_90,
                    "goals": row.goals,
                    "shots": row.shots,
                    "shots_on_target": row.shots_on_target,
                    "shots_on_target_pct": row.shots_on_target_pct,
                    "shots_per_90": row.shots_per_90,
                    "sot_per_90": row.sot_per_90,
                    "goals_per_shot": row.goals_per_shot,
                    "goals_per_sot": row.goals_per_sot,
                    "pk_scored": row.pk_scored,
                    "pk_att": row.pk_att,
                    "team_url": row.team_url,
                    "comp_url": row.comp_url,
                    "match_url": row.match_url,
                }

                stmt = pg_insert(PlayerShootingStats).values(**values)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["player_id", "season", "fk_team", "fk_comp"],
                    set_={
                        "fk_country": stmt.excluded.fk_country,
                        "min_per_90": stmt.excluded.min_per_90,
                        "goals": stmt.excluded.goals,
                        "shots": stmt.excluded.shots,
                        "shots_on_target": stmt.excluded.shots_on_target,
                        "shots_on_target_pct": stmt.excluded.shots_on_target_pct,
                        "shots_per_90": stmt.excluded.shots_per_90,
                        "sot_per_90": stmt.excluded.sot_per_90,
                        "goals_per_shot": stmt.excluded.goals_per_shot,
                        "goals_per_sot": stmt.excluded.goals_per_sot,
                        "pk_scored": stmt.excluded.pk_scored,
                        "pk_att": stmt.excluded.pk_att,
                        "team_url": stmt.excluded.team_url,
                        "comp_url": stmt.excluded.comp_url,
                        "match_url": stmt.excluded.match_url,
                        "updated_at": sa.func.now(),
                    },
                )
                await self._session.execute(stmt)
                count += 1

        return count
