"""PlayerMiscStatsRepository — upserts into tbl_player_misc_stats.

Tables managed:
    sch_fbref_shared.tbl_competition  — comp_name upsert (get or create comp_id)
    sch_fbref_football.tbl_player_misc_stats — main stats table

The caller owns the transaction; this repository never commits.
"""

from __future__ import annotations

import logging
import re

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.repository import repo_error_context
from domains.player_stats.models import PlayerMiscStatsRawData
from infrastructure.persistence.models.football.player_misc_stats import PlayerMiscStats

logger = logging.getLogger(__name__)


class PlayerMiscStatsRepository:
    """Persists player miscellaneous statistics into tbl_player_misc_stats.

    All methods are idempotent (ON CONFLICT ... DO UPDATE).
    The caller owns the transaction and must call session.commit().
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _resolve_comp_id(self, comp_url: str) -> int | None:
        m = re.search(r"/en/comps/(\d+)/", comp_url or "")
        if not m:
            return None
        return int(m.group(1))

    async def upsert_bulk(self, rows: list[PlayerMiscStatsRawData]) -> int:
        """Upsert a list of miscellaneous stats rows.

        For each row:
        1. Resolves fk_comp via comp_name upsert into tbl_competition.
        2. Upserts into tbl_player_misc_stats on PK conflict.

        Args:
            rows: Parsed rows from parse_player_misc_stats.

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
                comp_id = self._resolve_comp_id(row.comp_url or "")
                if comp_id is None:
                    continue
                row.fk_comp = comp_id

                values: dict[str, object] = {
                    "player_id": row.player_id,
                    "season": row.season,
                    "fk_team": row.fk_team,
                    "fk_country": row.fk_country,
                    "fk_comp": row.fk_comp,
                    "min_per_90": row.min_per_90,
                    "yellow_cards": row.yellow_cards,
                    "red_cards": row.red_cards,
                    "yellow_red_cards": row.yellow_red_cards,
                    "fouls": row.fouls,
                    "fouled": row.fouled,
                    "offsides": row.offsides,
                    "crosses": row.crosses,
                    "interceptions": row.interceptions,
                    "tackles_won": row.tackles_won,
                    "pk_won": row.pk_won,
                    "pk_conceded": row.pk_conceded,
                    "own_goals": row.own_goals,
                    "team_url": row.team_url,
                    "comp_url": row.comp_url,
                    "match_url": row.match_url,
                }

                stmt = pg_insert(PlayerMiscStats).values(**values)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["player_id", "season", "fk_team", "fk_comp"],
                    set_={
                        "fk_country": stmt.excluded.fk_country,
                        "min_per_90": stmt.excluded.min_per_90,
                        "yellow_cards": stmt.excluded.yellow_cards,
                        "red_cards": stmt.excluded.red_cards,
                        "yellow_red_cards": stmt.excluded.yellow_red_cards,
                        "fouls": stmt.excluded.fouls,
                        "fouled": stmt.excluded.fouled,
                        "offsides": stmt.excluded.offsides,
                        "crosses": stmt.excluded.crosses,
                        "interceptions": stmt.excluded.interceptions,
                        "tackles_won": stmt.excluded.tackles_won,
                        "pk_won": stmt.excluded.pk_won,
                        "pk_conceded": stmt.excluded.pk_conceded,
                        "own_goals": stmt.excluded.own_goals,
                        "team_url": stmt.excluded.team_url,
                        "comp_url": stmt.excluded.comp_url,
                        "match_url": stmt.excluded.match_url,
                        "updated_at": sa.func.now(),
                    },
                )
                await self._session.execute(stmt)
                count += 1

        return count
