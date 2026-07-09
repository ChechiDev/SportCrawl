"""ProvenanceRepository — async CRUD + domain queries for the provenance table.

The caller owns the transaction. This repository never commits.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from core.exceptions.repository import RepositoryError
from infrastructure.persistence.models.provenance import Provenance
from ports.repository import BaseRepository


class ProvenanceRepository(BaseRepository[Provenance]):
    """Async repository for the sch_infra.provenance append-only log.

    Inherits generic CRUD from BaseRepository[Provenance]:
        get(id) / create(entity) / update(entity) / delete(id) / list(**filters)

    Domain query:
        get_latest_by_url(url) — most recent scrape record for a given URL.
    """

    _model_class = Provenance

    async def get_latest_by_url(self, url: str) -> Provenance | None:
        """Return the most recently scraped Provenance record for *url*.

        Ordered by scraped_at DESC, limit 1. Returns None if no record exists
        for the given URL.

        Args:
            url: The scraped URL to look up.

        Returns:
            The Provenance row with the latest scraped_at, or None.

        Raises:
            RepositoryError: if the database query fails.
        """
        try:
            stmt = (
                select(Provenance)
                .where(Provenance.url == url)
                .order_by(Provenance.scraped_at.desc())
                .limit(1)
            )
            result = await self._session.execute(stmt)
            return result.scalar_one_or_none()
        except SQLAlchemyError as exc:
            raise RepositoryError(
                "get_latest_by_url failed",
                operation="get_latest_by_url",
                cause=exc,
            ) from exc

    async def update(self, entity: Provenance) -> Provenance:  # noqa: ARG002
        msg = "Provenance records are immutable; update forbidden"
        raise NotImplementedError(msg)

    async def delete(self, id: int) -> bool:  # noqa: ARG002
        msg = "Provenance records are immutable; delete forbidden"
        raise NotImplementedError(msg)
