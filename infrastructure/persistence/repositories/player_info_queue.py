"""PlayerInfoQueueRepository — claim/complete lifecycle for player_info scrape jobs.

Encodes the PENDING → IN_PROGRESS → DONE | FAILED state machine for
scrape_queue rows with job_type='player_info'. Uses SELECT FOR UPDATE SKIP LOCKED
for concurrent-safe job claiming.

The caller owns the transaction; this repository never commits.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import select, text
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.repository import RepositoryError, repo_error_context
from infrastructure.persistence.models.scrape_queue import ScrapeQueue, ScrapeStatus

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3


class PlayerInfoQueueRepository:
    """Async repository for player_info scrape_queue rows.

    State-machine methods:
        claim_next(job_type)       — atomically claim one PENDING row as IN_PROGRESS
        mark_done(job_id)          — IN_PROGRESS → DONE
        mark_failed(job_id, error) — IN_PROGRESS → PENDING (retry) or FAILED (ceiling)
        recover_stale(cutoff)      — reset stale IN_PROGRESS rows back to PENDING

    None of these methods call session.commit(). The caller owns the transaction.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def claim_next(self, job_type: str = "player_info") -> ScrapeQueue | None:
        """Atomically claim the next PENDING job of the given type.

        Issues SELECT FOR UPDATE SKIP LOCKED, then updates status=IN_PROGRESS
        and locked_at=now() on the claimed row.

        Args:
            job_type: Discriminator value in scrape_queue.job_type.

        Returns:
            The claimed ScrapeQueue row (now IN_PROGRESS), or None if no rows
            are pending.

        Raises:
            RepositoryError: if the database operation fails.
        """
        async with repo_error_context("claim_next", "claim_next failed"):
            stmt = (
                select(ScrapeQueue)
                .where(
                    ScrapeQueue.status == ScrapeStatus.PENDING,
                    ScrapeQueue.job_type == job_type,
                )
                .order_by(ScrapeQueue.id)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            result = await self._session.execute(stmt)
            row = result.scalars().first()
            if row is None:
                return None

            row.status = ScrapeStatus.IN_PROGRESS
            row.locked_at = datetime.now(UTC)
            await self._session.flush()
            return row

    async def _get_job_or_raise(self, job_id: int, operation: str) -> ScrapeQueue:
        row = await self._session.get(ScrapeQueue, job_id)
        if row is None:
            raise RepositoryError(
                f"{operation}: job {job_id} not found",
                operation=operation,
            )
        return row

    async def mark_done(self, job_id: int) -> None:
        """Transition *job_id* to DONE and record completion time.

        Clears locked_at and sets completed_at. Flushes but does NOT commit.

        Args:
            job_id: Primary key of the ScrapeQueue row.

        Raises:
            RepositoryError: if the row is not found or the flush fails.
        """
        async with repo_error_context("mark_done", "mark_done failed"):
            row = await self._get_job_or_raise(job_id, "mark_done")
            row.status = ScrapeStatus.DONE
            row.completed_at = datetime.now(UTC)
            row.locked_at = None
            await self._session.flush()

    async def mark_failed(self, job_id: int, error: str) -> None:
        """Transition *job_id* to FAILED (or re-queue as PENDING) on error.

        Increments retry_count. If retry_count >= _MAX_RETRIES: FAILED + completed_at.
        Otherwise: PENDING + locked_at=None (retryable).

        Args:
            job_id: Primary key of the ScrapeQueue row.
            error: Human-readable error description.

        Raises:
            RepositoryError: if the row is not found or the flush fails.
        """
        async with repo_error_context("mark_failed", "mark_failed failed"):
            row = await self._get_job_or_raise(job_id, "mark_failed")
            row.retry_count += 1
            row.error_message = error
            row.locked_at = None

            if row.retry_count >= _MAX_RETRIES:
                row.status = ScrapeStatus.FAILED
                row.completed_at = datetime.now(UTC)
            else:
                row.status = ScrapeStatus.PENDING

            await self._session.flush()

    async def recover_stale(self, cutoff_minutes: int = 30) -> int:
        """Reset IN_PROGRESS rows with job_type='player_info' older than the cutoff.

        Issues a single UPDATE back to PENDING + locked_at=NULL.
        Caller owns the transaction.

        Args:
            cutoff_minutes: Rows locked longer than this interval are reset.

        Returns:
            Number of rows reset.

        Raises:
            RepositoryError: if the UPDATE fails.
        """
        async with repo_error_context("recover_stale", "recover_stale failed"):
            stmt = text(
                """
                UPDATE sch_infra.scrape_queue
                   SET status    = 'PENDING',
                       locked_at = NULL
                 WHERE status    = 'IN_PROGRESS'
                   AND job_type  = 'player_info'
                   AND locked_at < now() - (:cutoff * interval '1 minute')
                """
            )
            result = await self._session.execute(stmt, {"cutoff": cutoff_minutes})
            rowcount = cast(CursorResult, result).rowcount  # type: ignore[type-arg]
            if rowcount is None:
                raise RepositoryError(
                    "recover_stale: DML result has no rowcount",
                    operation="recover_stale",
                )
            return rowcount
