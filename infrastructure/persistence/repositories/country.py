"""CountryRepository — upserts confederation, country, and flag rows in FK-safe order.

Does NOT inherit BaseRepository because it coordinates three tables rather than
wrapping a single ORM model.  The caller owns the transaction; this repository
never calls session.commit().
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.repository import RepositoryError
from domains.country.models import CountryRawData
from infrastructure.persistence.models.shared.confederation import Confederation
from infrastructure.persistence.models.shared.country import Country
from infrastructure.persistence.models.shared.flag import Flag


class CountryRepository:
    """Persists country-related data across three sch_shared tables.

    Upsert order per row:
        1. tbl_confederations  (if confederation is present)
        2. tbl_countries
        3. tbl_flags

    The caller owns the transaction and must call session.commit() after upsert().
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, rows: list[CountryRawData]) -> None:
        """Upsert a list of CountryRawData rows in FK-safe order.

        Args:
            rows: Parsed country data from the scraper.

        Raises:
            RepositoryError: if any database operation fails.
        """
        try:
            for row in rows:
                conf_id: int | None = None

                # 1. Upsert confederation (if present)
                if row.confederation is not None:
                    stmt_conf = (
                        pg_insert(Confederation)
                        .values(conf_name=row.confederation)
                        .on_conflict_do_update(
                            constraint="uq_confederations_conf_name",
                            set_={"conf_name": sa.text("EXCLUDED.conf_name")},
                        )
                        .returning(Confederation.conf_id)
                    )
                    result_conf = await self._session.execute(stmt_conf)
                    conf_id = result_conf.scalar_one()

                # 2. Upsert country
                stmt_country = (
                    pg_insert(Country)
                    .values(
                        country_id=row.country_id,
                        country_name=row.country_name,
                        country_url=row.country_url,
                        fk_conf=conf_id,
                    )
                    .on_conflict_do_update(
                        index_elements=["country_id"],
                        set_={
                            "country_name": row.country_name,
                            "country_url": row.country_url,
                            "fk_conf": conf_id,
                            "updated_at": func.now(),
                        },
                    )
                    .returning(Country.country_id)
                )
                result_country = await self._session.execute(stmt_country)
                country_id_value: str = result_country.scalar_one()

                # 3. Upsert flag
                stmt_flag = (
                    pg_insert(Flag)
                    .values(
                        flag_id=row.flag_id,
                        flag_url=row.flag_url,
                        fk_country=country_id_value,
                    )
                    .on_conflict_do_update(
                        index_elements=["fk_country"],
                        set_={
                            "flag_id": row.flag_id,
                            "flag_url": row.flag_url,
                        },
                    )
                )
                await self._session.execute(stmt_flag)

        except SQLAlchemyError as exc:
            raise RepositoryError(
                "CountryRepository.upsert failed",
                operation="upsert",
                cause=exc,
            ) from exc
