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

        Args:
            rows: Parsed country-squad data from the scraper.

        Raises:
            RepositoryError: if any database operation fails.
        """
        try:
            for row in rows:
                # 1. Upsert confederation (if present) — ON CONFLICT DO NOTHING
                if row.confederation is not None:
                    stmt_conf = (
                        pg_insert(Confederation)
                        .values(conf_name=row.confederation)
                        .on_conflict_do_nothing(constraint="uq_confederations_conf_name")
                    )
                    await self._session.execute(stmt_conf)

                # 2. Upsert country-squad row — ON CONFLICT (fk_country) DO UPDATE
                stmt_squad = (
                    pg_insert(CountrySquads)
                    .values(
                        fk_country=row.fk_country,
                        fk_flag=row.fk_flag,
                        clubs_url=row.clubs_url,
                        nat_team_men_url=row.nat_team_men_url,
                        nat_team_women_url=row.nat_team_women_url,
                        fbref_men_squad_id=row.fbref_men_squad_id,
                        fbref_women_squad_id=row.fbref_women_squad_id,
                    )
                    .on_conflict_do_update(
                        index_elements=["fk_country"],
                        set_={
                            "fk_flag": row.fk_flag,
                            "clubs_url": row.clubs_url,
                            "nat_team_men_url": row.nat_team_men_url,
                            "nat_team_women_url": row.nat_team_women_url,
                            "fbref_men_squad_id": row.fbref_men_squad_id,
                            "fbref_women_squad_id": row.fbref_women_squad_id,
                            "updated_at": func.now(),
                        },
                    )
                )
                await self._session.execute(stmt_squad)

        except SQLAlchemyError as exc:
            raise RepositoryError(
                "CountrySquadsRepository.upsert failed",
                operation="upsert",
                cause=exc,
            ) from exc
