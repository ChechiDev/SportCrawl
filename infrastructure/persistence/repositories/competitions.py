from __future__ import annotations

import logging
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.repository import repo_error_context
from domains.competitions.models import CompetitionRawData
from infrastructure.persistence.models.shared.comp_type import CompType
from infrastructure.persistence.models.shared.competition import Competition
from infrastructure.persistence.models.shared.confederation import Confederation
from infrastructure.persistence.models.shared.flag import Flag

logger = logging.getLogger(__name__)


class CompetitionsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _resolve_comp_type_id(self, comp_type_name: str) -> int:
        stmt = pg_insert(CompType).values(comp_type_name=comp_type_name)
        stmt = stmt.on_conflict_do_nothing(constraint="uq_tbl_comp_type_comp_type_name")
        await self._session.execute(stmt)
        result = await self._session.execute(
            sa.select(CompType.comp_type_id).where(
                CompType.comp_type_name == comp_type_name
            )
        )
        return int(result.scalar_one())

    async def _resolve_gender_id(self, gender: str) -> int:
        from infrastructure.persistence.models.shared.gender import Gender

        result = await self._session.execute(
            sa.select(Gender.id).where(Gender.gender == gender)
        )
        return int(result.scalar_one())

    async def _resolve_flag_id(self, country_id: str) -> str | None:
        result = await self._session.execute(
            sa.select(Flag.flag_id).where(Flag.fk_country == country_id)
        )
        return result.scalar_one_or_none()

    async def _resolve_conf_id(self, conf_name: str) -> int:
        stmt = pg_insert(Confederation).values(conf_name=conf_name)
        stmt = stmt.on_conflict_do_nothing(constraint="uq_confederations_conf_name")
        await self._session.execute(stmt)

        result = await self._session.execute(
            sa.select(Confederation.conf_id).where(
                Confederation.conf_name == conf_name
            )
        )
        return int(result.scalar_one())

    async def upsert_bulk(self, rows: list[CompetitionRawData]) -> int:
        if not rows:
            return 0

        count = 0
        for row in rows:
            async with repo_error_context("upsert_bulk", "upsert_bulk row failed"):
                comp_type_id = await self._resolve_comp_type_id(row.comp_type_name)
                gender_id = await self._resolve_gender_id(row.gender)

                conf_id: int | None = None
                if row.conf_name is not None:
                    conf_id = await self._resolve_conf_id(row.conf_name)

                flag_id = row.flag_id
                if flag_id is None and row.country_id is not None:
                    flag_id = await self._resolve_flag_id(row.country_id)

                values: dict[str, object] = {
                    "comp_id": row.comp_id,
                    "comp_name": row.comp_name,
                    "fk_comp_type": comp_type_id,
                    "fk_gender": gender_id,
                    "fk_conf": conf_id,
                    "fk_flag": flag_id,
                    "fk_country": row.country_id,
                    "first_season": row.first_season,
                    "last_season": row.last_season,
                }

                stmt = pg_insert(Competition).values(**values)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["comp_id"],
                    set_={
                        "comp_name": stmt.excluded.comp_name,
                        "fk_comp_type": stmt.excluded.fk_comp_type,
                        "fk_gender": stmt.excluded.fk_gender,
                        "fk_conf": stmt.excluded.fk_conf,
                        "fk_flag": stmt.excluded.fk_flag,
                        "fk_country": stmt.excluded.fk_country,
                        "first_season": stmt.excluded.first_season,
                        "last_season": stmt.excluded.last_season,
                        "updated_at": sa.func.now(),
                    },
                )
                await self._session.execute(stmt)
                count += 1

                # Co-insert backend scheduling row — same transaction, best-effort.
                # comp_url is no longer in tbl_competition; use the Python-side value.
                try:
                    if row.comp_url:
                        await self._session.execute(
                            sa.text(
                                """
                                INSERT INTO sch_fbref_backend.tbl_competition_urls
                                    (fk_comp, url_type, url, cadence_hours, priority,
                                     status, next_scrape_at, created_at, updated_at, retry_count)
                                VALUES (:comp_id, 'index', :url, 720, 3,
                                        'PENDING', now(), now(), now(), 0)
                                ON CONFLICT (fk_comp, url_type) DO NOTHING
                                """
                            ),
                            {"comp_id": row.comp_id, "url": row.comp_url},
                        )
                except Exception:
                    logger.warning(
                        "Backend co-insert failed for competition %s; skipping",
                        row.comp_id,
                        exc_info=True,
                    )

        return count
