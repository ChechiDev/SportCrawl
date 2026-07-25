"""TeamListQueueRepository — claim/complete lifecycle for team_list scrape jobs.

Encodes the PENDING → IN_PROGRESS → DONE | FAILED state machine for
scrape_queue rows with job_type='team_list'. Delegates to the generic
ScrapeQueueRepository base class, with an optional country-scoped claim.

The caller owns the transaction; this repository never commits.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.repository import repo_error_context
from infrastructure.persistence.models.scrape_queue import ScrapeQueue, ScrapeStatus
from infrastructure.persistence.models.shared.country_squads import CountrySquads
from infrastructure.persistence.repositories.scrape_queue import ScrapeQueueRepository


class TeamListQueueRepository(ScrapeQueueRepository):
    """Async repository for team_list scrape_queue rows.

    Inherits the full state-machine (claim_next, mark_done, mark_failed,
    recover_all_stale) from ScrapeQueueRepository with job_type='team_list'.

    When a country_filter is provided to claim_next, only rows whose url
    matches a clubs_url belonging to one of the given fk_country values are
    eligible for claiming (--country mode). When None, any PENDING team_list
    row may be claimed (--all mode).
    """

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, job_type="team_list")

    async def claim_next(self) -> ScrapeQueue | None:
        """Claim the next PENDING team_list job (no country filter).

        Delegates to claim_next_filtered(None) for LSP-compatible override.

        Returns:
            The claimed ScrapeQueue row (status set to IN_PROGRESS), or None
            if no PENDING row exists.
        """
        return await self.claim_next_filtered(None)

    async def claim_next_filtered(
        self,
        country_filter: set[str] | None = None,
    ) -> ScrapeQueue | None:
        """Claim the next PENDING team_list job with optional country filter.

        When country_filter is set (--country mode), restrict claims to rows
        whose url matches a clubs_url belonging to one of the given fk_country
        values. When None, claim any PENDING team_list row (--all mode).

        Args:
            country_filter: Set of fk_country codes to restrict claiming to,
                or None to claim any PENDING team_list row.

        Returns:
            The claimed ScrapeQueue row (status set to IN_PROGRESS), or None
            if no eligible PENDING row exists.
        """
        async with repo_error_context(
            "claim_next_filtered", "claim_next_filtered failed"
        ):
            stmt = (
                select(ScrapeQueue)
                .where(
                    ScrapeQueue.status == ScrapeStatus.PENDING,
                    ScrapeQueue.job_type == self._job_type,
                )
                .order_by(ScrapeQueue.id)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if country_filter is not None:
                stmt = stmt.where(
                    ScrapeQueue.url.in_(
                        select(CountrySquads.clubs_url).where(
                            CountrySquads.fk_country.in_(country_filter)
                        )
                    )
                )
            result = await self._session.execute(stmt)
            row = result.scalars().first()
            if row is None:
                return None
            row.status = ScrapeStatus.IN_PROGRESS
            row.locked_at = datetime.now(UTC)
            await self._session.flush()
            return row
