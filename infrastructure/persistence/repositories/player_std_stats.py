"""PlayerStdStatsRepository — upserts player standard stats into tbl_player_std_stats.

Tables managed:
    sch_fbref_football.tbl_player_std_stats — main stats table

The caller owns the transaction; this repository never commits.
"""

from __future__ import annotations

import logging

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.repository import repo_error_context
from domains.player_stats.models import PlayerStdStatsRawData
from infrastructure.persistence.models.football.player_std_stats import PlayerStdStats

logger = logging.getLogger(__name__)


class PlayerStdStatsRepository:
    """Persists player standard statistics into tbl_player_std_stats.

    All methods are idempotent (ON CONFLICT ... DO UPDATE).
    The caller owns the transaction and must call session.commit().
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_bulk(self, rows: list[PlayerStdStatsRawData]) -> int:
        """Upsert a list of standard stats rows.

        For each row:
        1. Uses comp_id extracted by the scraper layer directly (no URL resolution).
        2. Upserts into tbl_player_std_stats on PK conflict.

        Args:
            rows: Parsed rows from parse_player_std_stats.

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

                # Skip rows referencing competitions not in our table to avoid FK violations.
                comp_check = await self._session.execute(
                    sa.text(
                        "SELECT 1 FROM sch_fbref_shared.tbl_competition"
                        " WHERE comp_id = :cid"
                    ),
                    {"cid": row.fk_comp},
                )
                if not comp_check.scalar():
                    logger.debug(
                        "Skipping stats row: comp %s not in tbl_competition (player %s)",
                        row.fk_comp,
                        row.player_id,
                    )
                    continue

                values: dict[str, object] = {
                    "player_id": row.player_id,
                    "season": row.season,
                    "fk_team": row.fk_team,
                    "fk_country": row.fk_country,
                    "fk_comp": row.fk_comp,
                    "age": row.age,
                    "matches": row.matches,
                    "starts": row.starts,
                    "minutes": row.minutes,
                    "min_per_90": row.min_per_90,
                    "goals": row.goals,
                    "assists": row.assists,
                    "goals_assists": row.goals_assists,
                    "goals_pk": row.goals_pk,
                    "pk_scored": row.pk_scored,
                    "pk_att": row.pk_att,
                    "yellow_cards": row.yellow_cards,
                    "red_cards": row.red_cards,
                    "goals_p90": row.goals_p90,
                    "assists_p90": row.assists_p90,
                    "goals_assists_p90": row.goals_assists_p90,
                    "goals_pk_p90": row.goals_pk_p90,
                    "goals_assists_pk_p90": row.goals_assists_pk_p90,
                    "team_url": row.team_url,
                    "comp_url": None,
                    "match_url": row.match_url,
                }

                stmt = pg_insert(PlayerStdStats).values(**values)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["player_id", "season", "fk_team", "fk_comp"],
                    set_={
                        "fk_country": stmt.excluded.fk_country,
                        "age": stmt.excluded.age,
                        "matches": stmt.excluded.matches,
                        "starts": stmt.excluded.starts,
                        "minutes": stmt.excluded.minutes,
                        "min_per_90": stmt.excluded.min_per_90,
                        "goals": stmt.excluded.goals,
                        "assists": stmt.excluded.assists,
                        "goals_assists": stmt.excluded.goals_assists,
                        "goals_pk": stmt.excluded.goals_pk,
                        "pk_scored": stmt.excluded.pk_scored,
                        "pk_att": stmt.excluded.pk_att,
                        "yellow_cards": stmt.excluded.yellow_cards,
                        "red_cards": stmt.excluded.red_cards,
                        "goals_p90": stmt.excluded.goals_p90,
                        "assists_p90": stmt.excluded.assists_p90,
                        "goals_assists_p90": stmt.excluded.goals_assists_p90,
                        "goals_pk_p90": stmt.excluded.goals_pk_p90,
                        "goals_assists_pk_p90": stmt.excluded.goals_assists_pk_p90,
                        "team_url": stmt.excluded.team_url,
                        "comp_url": stmt.excluded.comp_url,
                        "match_url": stmt.excluded.match_url,
                        "updated_at": sa.func.now(),
                    },
                )
                await self._session.execute(stmt)
                count += 1

        return count
