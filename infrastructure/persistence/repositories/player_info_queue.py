"""PlayerInfoQueueRepository — claim/complete lifecycle for player_info scrape jobs."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from core.application.retry_policy import is_terminal
from core.exceptions.repository import repo_error_context
from infrastructure.persistence.models.scrape_queue import ScrapeQueue, ScrapeStatus
from infrastructure.persistence.repositories.backend_urls import BackendUrlRepository
from infrastructure.persistence.repositories.scrape_queue import ScrapeQueueRepository
from infrastructure.persistence.session import get_session


class PlayerInfoQueueRepository(ScrapeQueueRepository):
    """Async repository for player_info scrape_queue rows.

    Inherits the full state-machine from ScrapeQueueRepository with
    job_type='player_info'. Overrides mark_failed to enforce a terminal
    retry ceiling: jobs exceeding max_retry_count transition to FAILED
    instead of re-queuing indefinitely.
    """

    def __init__(self, session: AsyncSession, max_retry_count: int = 5) -> None:
        super().__init__(session, job_type="player_info")
        self._max_retry_count = max_retry_count

    async def claim_next(self) -> ScrapeQueue | None:
        """Claim the next PENDING player_info job."""
        return await super().claim_next()

    async def mark_failed(self, job_id: int, error: str) -> None:
        """Re-queue or terminate a failed job based on the retry ceiling.

        Below the ceiling: transitions to PENDING (retryable).
        At or above the ceiling: transitions to FAILED (terminal).
        """
        async with repo_error_context("mark_failed", "mark_failed failed"):
            row = await self._get_job_or_raise(job_id, "mark_failed")
            row.retry_count += 1
            row.error_message = error
            row.locked_at = None
            if is_terminal(row.retry_count - 1, self._max_retry_count):
                row.status = ScrapeStatus.FAILED
                row.completed_at = datetime.now(UTC)
            else:
                row.status = ScrapeStatus.PENDING
            await self._session.flush()


async def recover_failed_job(
    job_id: int,
    session_factory: object,
) -> None:
    """Atomically recover a FAILED scrape_queue row and its STALE tbl_player_urls row.

    Validates the pair relationship before applying any changes. Both rows must be
    in their terminal states (FAILED / STALE) and share the same fk_url_registry_id.
    Resets both to PENDING in one commit.

    Raises:
        ValueError: if the job is missing, wrong type, wrong state, or the URL
                    registry row is missing, wrong state, or the IDs do not match.
    """
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession as _AS
    from sqlalchemy.ext.asyncio import async_sessionmaker

    sf: async_sessionmaker[_AS] = session_factory  # type: ignore[assignment]

    async with get_session(sf) as session:
        # Lock queue row
        queue_row = await session.get(ScrapeQueue, job_id, with_for_update=True)
        if queue_row is None:
            raise ValueError(f"Job {job_id} not found")
        if queue_row.job_type != "player_info":
            raise ValueError(
                f"Job {job_id} has job_type={queue_row.job_type!r},"
                " expected 'player_info'"
            )
        if queue_row.status != ScrapeStatus.FAILED:
            raise ValueError(
                f"Job {job_id} is in state {queue_row.status!r}, expected FAILED"
            )
        if queue_row.fk_url_registry_id is None:
            raise ValueError(f"Job {job_id} has no associated tbl_player_urls row")

        # Lock URL row and verify relationship
        url_result = await session.execute(
            text(
                "SELECT id, status FROM sch_fbref_backend.tbl_player_urls"
                " WHERE id = :url_id FOR UPDATE"
            ),
            {"url_id": queue_row.fk_url_registry_id},
        )
        url_row = url_result.one_or_none()
        if url_row is None:
            raise ValueError(
                f"tbl_player_urls row {queue_row.fk_url_registry_id} not found"
            )
        if url_row.status != "STALE":
            raise ValueError(
                f"tbl_player_urls row {url_row.id} is in state"
                f" {url_row.status!r}, expected STALE"
            )

        # Apply both transitions
        queue_row.status = ScrapeStatus.PENDING
        queue_row.retry_count = 0
        queue_row.error_message = None
        queue_row.completed_at = None
        queue_row.locked_at = None

        await BackendUrlRepository(session).recover_stale_url(
            "tbl_player_urls", url_row.id
        )

        await session.commit()
