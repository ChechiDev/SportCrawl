"""CountrySquadsRepository — upserts confederation and country-squad rows.

Does NOT inherit BaseRepository because it coordinates two tables rather than
wrapping a single ORM model. The caller owns the transaction; this repository
never calls session.commit().
"""

from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.repository import RepositoryError
from domains.club.models import CountrySquad
from infrastructure.persistence.models.shared.confederation import Confederation
from infrastructure.persistence.models.shared.country_squads import CountrySquads


class CountrySquadsRepository:
    """Persists club-discovery data across tbl_confederations and tbl_country_squads.

    Upsert order per row:
        1. tbl_confederations  (if confederation is present) — ON CONFLICT DO NOTHING
        2. tbl_country_squads  — ON CONFLICT (fk_country) DO UPDATE all mutable columns

    The caller owns the transaction and must call session.commit() after upsert().
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, rows: list[CountrySquad]) -> None:
        """Upsert a list of CountrySquad rows in FK-safe order.

        Performs two batched statements:
        1. Insert all unique confederations — ON CONFLICT DO NOTHING.
        2. Insert all squad rows — ON CONFLICT (pk) DO UPDATE all mutable columns.

        Args:
            rows: Parsed country-squad data from the scraper.

        Raises:
            RepositoryError: if any database operation fails.
        """
        if not rows:
            return

        try:
            # 1. Batch-insert unique confederations — ON CONFLICT DO NOTHING
            unique_confederations = {
                row.confederation
                for row in rows
                if row.confederation is not None
            }
            if unique_confederations:
                stmt_conf = pg_insert(Confederation).values(
                    [{"conf_name": name} for name in unique_confederations]
                ).on_conflict_do_nothing(constraint="uq_confederations_conf_name")
                await self._session.execute(stmt_conf)

            # 2. Batch-upsert all squad rows — ON CONFLICT (pk) DO UPDATE
            squad_values = [
                {
                    "fk_country": row.fk_country,
                    "fk_flag": row.fk_flag,
                    "clubs_url": row.clubs_url,
                    "nat_team_men_url": row.nat_team_men_url,
                    "nat_team_women_url": row.nat_team_women_url,
                    "fbref_men_squad_id": row.fbref_men_squad_id,
                    "fbref_women_squad_id": row.fbref_women_squad_id,
                }
                for row in rows
            ]
            insert_stmt = pg_insert(CountrySquads).values(squad_values)
            stmt_squad = insert_stmt.on_conflict_do_update(
                constraint="tbl_country_squads_pkey",
                set_={
                    "fk_flag": insert_stmt.excluded.fk_flag,
                    "clubs_url": insert_stmt.excluded.clubs_url,
                    "nat_team_men_url": insert_stmt.excluded.nat_team_men_url,
                    "nat_team_women_url": insert_stmt.excluded.nat_team_women_url,
                    "fbref_men_squad_id": insert_stmt.excluded.fbref_men_squad_id,
                    "fbref_women_squad_id": insert_stmt.excluded.fbref_women_squad_id,
                    "updated_at": func.now(),
                },
            )
            await self._session.execute(stmt_squad)

        except SQLAlchemyError as exc:
            raise RepositoryError(
                "CountrySquadsRepository.upsert failed",
                operation="upsert",
                cause=exc,
            ) from exc
