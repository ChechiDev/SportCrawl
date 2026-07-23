"""TeamsRepository — upserts competition and team rows.

Does NOT inherit BaseRepository because it coordinates two tables rather than
wrapping a single ORM model. The caller owns the transaction; this repository
never calls session.commit().
"""

from __future__ import annotations

import logging

import sqlalchemy as sa
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.repository import RepositoryError
from domains.club.models import Team
from infrastructure.persistence.models.shared.competition import Competition
from infrastructure.persistence.models.shared.gender import Gender
from infrastructure.persistence.models.shared.teams import Teams

logger = logging.getLogger(__name__)


class TeamsRepository:
    """Persists team-discovery data across tbl_competition and tbl_teams.

    Upsert order:
        1. tbl_competition (unique comp names) — ON CONFLICT DO NOTHING
        2. Fetch comp_id map and gender_id map
        3. tbl_teams batch upsert — ON CONFLICT (team_id) DO UPDATE

    The caller owns the transaction and must call session.commit() after upsert().
    """

    def __init__(
        self,
        session: AsyncSession,
        gender_map: dict[str, int] | None = None,
    ) -> None:
        self._session = session
        self._gender_map = gender_map

    async def upsert(self, rows: list[Team]) -> None:
        """Upsert a list of Team rows in FK-safe order.

        Args:
            rows: Parsed team data from the scraper.

        Raises:
            RepositoryError: if any database operation fails.
        """
        if not rows:
            return

        try:
            # Step 1: upsert unique competitions
            comp_map: dict[str, int] = {}
            comp_names = {r.comp_name for r in rows if r.comp_name}
            if comp_names:
                stmt_comp = pg_insert(Competition).values(
                    [{"comp_name": name} for name in comp_names]
                )
                stmt_comp = stmt_comp.on_conflict_do_nothing(
                    constraint="uq_tbl_competition_comp_name"
                )
                await self._session.execute(stmt_comp)

                # Fetch all comp IDs for the names we just ensured exist
                fetch_result = await self._session.execute(
                    sa.select(Competition.comp_id, Competition.comp_name).where(
                        Competition.comp_name.in_(comp_names)
                    )
                )
                comp_map = {row.comp_name: row.comp_id for row in fetch_result}

            # Step 2: load gender lookup {gender_value: id} (skip if pre-loaded)
            if self._gender_map is not None:
                gender_map = self._gender_map
            else:
                gender_result = await self._session.execute(
                    sa.select(Gender.id, Gender.gender)
                )
                gender_map = {row.gender: row.id for row in gender_result}

            # Step 3: batch upsert teams
            values = []
            for r in rows:
                fk_gender = gender_map.get(r.gender_raw)
                if fk_gender is None:
                    logger.warning(
                        "Unknown gender_raw=%r, skipping team %s",
                        r.gender_raw,
                        r.team_id,
                    )
                    continue
                values.append(
                    {
                        "team_id": r.team_id,
                        "team_name": r.team_name,
                        "fk_country": r.fk_country,
                        "fk_gender": fk_gender,
                        "fk_comp": comp_map.get(r.comp_name) if r.comp_name else None,
                        "team_from": r.team_from,
                        "team_to": r.team_to,
                        "team_url": r.team_url,
                    }
                )
            if values:
                insert_stmt = pg_insert(Teams).values(values)
                stmt_teams = insert_stmt.on_conflict_do_update(
                    constraint="pk_tbl_teams",
                    set_={
                        "team_name": insert_stmt.excluded.team_name,
                        "fk_country": insert_stmt.excluded.fk_country,
                        "fk_gender": insert_stmt.excluded.fk_gender,
                        "fk_comp": insert_stmt.excluded.fk_comp,
                        "team_from": insert_stmt.excluded.team_from,
                        "team_to": insert_stmt.excluded.team_to,
                        "team_url": insert_stmt.excluded.team_url,
                        "updated_at": func.now(),
                    },
                )
                await self._session.execute(stmt_teams)

        except SQLAlchemyError as exc:
            raise RepositoryError(
                "TeamsRepository.upsert failed",
                operation="upsert",
                cause=exc,
            ) from exc
