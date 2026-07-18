"""PlayerInfoQueueRepository — claim/complete lifecycle for player_info scrape jobs.

Encodes the PENDING → IN_PROGRESS → DONE | FAILED state machine for
scrape_queue rows with job_type='player_info'. Delegates to the generic
ScrapeQueueRepository base class.

The caller owns the transaction; this repository never commits.
"""

from __future__ import annotations

from typing import cast

from sqlalchemy import text
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.repository import RepositoryError, repo_error_context
from infrastructure.persistence.models.scrape_queue import ScrapeQueue
from infrastructure.persistence.repositories.scrape_queue import ScrapeQueueRepository


class PlayerInfoQueueRepository(ScrapeQueueRepository):
    """Async repository for player_info scrape_queue rows.

    Inherits the full state-machine (claim_next, mark_done, mark_failed,
    recover_stale) from ScrapeQueueRepository with job_type='player_info'.
    """

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, job_type="player_info")

    async def claim_next(self) -> ScrapeQueue | None:
        """Claim the next PENDING player_info job."""
        return await super().claim_next()

    async def recover_failed(self) -> int:
        """Reset all FAILED player_info jobs back to PENDING."""
        async with repo_error_context("recover_failed", "recover_failed failed"):
            stmt = text(
                """
                UPDATE sch_infra.scrape_queue
                   SET status        = 'PENDING',
                       retry_count   = 0,
                       error_message = NULL,
                       completed_at  = NULL
                 WHERE status   = 'FAILED'
                   AND job_type = :job_type
                """
            )
            result = await self._session.execute(stmt, {"job_type": self._job_type})
            rowcount = cast(CursorResult, result).rowcount  # type: ignore[type-arg]
            if rowcount is None:
                raise RepositoryError(
                    "recover_failed: DML result has no rowcount",
                    operation="recover_failed",
                )
            return rowcount
