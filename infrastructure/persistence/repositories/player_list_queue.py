"""PlayerListQueueRepository — claim/complete lifecycle for player_list scrape jobs.

Encodes the PENDING → IN_PROGRESS → DONE | FAILED state machine for
scrape_queue rows with job_type='player_list'. Delegates to the generic
ScrapeQueueRepository base class.

The caller owns the transaction; this repository never commits.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.persistence.models.scrape_queue import ScrapeQueue
from infrastructure.persistence.repositories.scrape_queue import ScrapeQueueRepository


class PlayerListQueueRepository(ScrapeQueueRepository):
    """Async repository for player_list scrape_queue rows.

    Inherits the full state-machine (claim_next, mark_done, mark_failed,
    recover_stale) from ScrapeQueueRepository with job_type='player_list'.
    """

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, job_type="player_list")

    async def claim_next(self) -> ScrapeQueue | None:
        """Claim the next PENDING player_list job."""
        return await super().claim_next()
