"""ScrapeQueue repositories — async state-machine repositories for scrape_queue.

Two repository classes:
- ScrapeQueueRepository: generic base parameterized by job_type, used by
  PlayerInfoQueueRepository and other per-job-type repositories.
- ScrapeQueueJobRepository: JobLoop-oriented repository that works on the full
  table (list_pending, mark_in_progress, etc.) regardless of job_type.

The caller owns the transaction; neither class ever commits.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import select, text
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import SQLAlchemyError

from core.exceptions.repository import RepositoryError, repo_error_context
from infrastructure.persistence.models.scrape_queue import ScrapeQueue, ScrapeStatus
from ports.repository import BaseRepository

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3


class ScrapeQueueRepository:
    """Generic async repository for scrape_queue rows, parameterized by job_type.

    Provides the claim_next / mark_done / mark_failed / recover_stale state machine
    for a fixed job_type discriminator. Concrete subclasses set self._job_type in
    their __init__ by calling super().__init__(session, job_type=...).

    None of these methods call session.commit(). The caller owns the transaction.
    """

    def __init__(self, session: object, job_type: str) -> None:
        from sqlalchemy.ext.asyncio import AsyncSession
        self._session: AsyncSession = session  # type: ignore[assignment]
        self._job_type = job_type

    async def claim_next(self) -> ScrapeQueue | None:
        """Atomically claim the next PENDING job of this repository's job_type."""
        async with repo_error_context("claim_next", "claim_next failed"):
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
        """Transition job_id to DONE and record completion time."""
        async with repo_error_context("mark_done", "mark_done failed"):
            row = await self._get_job_or_raise(job_id, "mark_done")
            row.status = ScrapeStatus.DONE
            row.completed_at = datetime.now(UTC)
            row.locked_at = None
            await self._session.flush()

    async def mark_failed(self, job_id: int, error: str) -> None:
        """Transition job_id to FAILED (or re-queue as PENDING) on error."""
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
        """Reset IN_PROGRESS rows with this job_type older than the cutoff."""
        async with repo_error_context("recover_stale", "recover_stale failed"):
            stmt = text(
                """
                UPDATE sch_infra.scrape_queue
                   SET status    = 'PENDING',
                       locked_at = NULL
                 WHERE status    = 'IN_PROGRESS'
                   AND job_type  = :job_type
                   AND locked_at < now() - (:cutoff * interval '1 minute')
                """
            )
            result = await self._session.execute(
                stmt, {"job_type": self._job_type, "cutoff": cutoff_minutes}
            )
            rowcount = cast(CursorResult, result).rowcount  # type: ignore[type-arg]
            if rowcount is None:
                raise RepositoryError(
                    "recover_stale: DML result has no rowcount",
                    operation="recover_stale",
                )
            return rowcount


class ScrapeQueueJobRepository(BaseRepository[ScrapeQueue]):
    """Async repository for the sch_infra.scrape_queue table.

    Inherits generic CRUD from BaseRepository[ScrapeQueue].

    State-machine methods:
        list_pending(limit) — fetch PENDING rows in insertion order
        mark_in_progress(row) — PENDING → IN_PROGRESS
        mark_done(row) — IN_PROGRESS → DONE
        mark_failed(row, error, settings) — IN_PROGRESS → FAILED/PENDING

    None of these methods call session.commit(). The caller owns the transaction.
    """

    _model_class = ScrapeQueue

    async def list_pending(self, limit: int) -> list[ScrapeQueue]:
        """Return up to *limit* PENDING rows ordered by id (insertion order).

        Args:
            limit: Maximum number of rows to return.

        Returns:
            List of ScrapeQueue rows with status=PENDING, oldest first.

        Raises:
            RepositoryError: if the database query fails.
        """
        try:
            stmt = (
                select(ScrapeQueue)
                .where(ScrapeQueue.status == ScrapeStatus.PENDING)
                .order_by(ScrapeQueue.id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
            result = await self._session.execute(stmt)
            return list(result.scalars().all())
        except SQLAlchemyError as exc:
            raise RepositoryError(
                "list_pending failed",
                operation="list_pending",
                cause=exc,
            ) from exc

    async def recover_stale(
        self, domain: str, ttl_minutes: int = 30
    ) -> int:
        """Reset IN_PROGRESS rows older than *ttl_minutes* back to PENDING.

        Issues a single UPDATE that sets status=PENDING and locked_at=NULL for
        all IN_PROGRESS rows whose locked_at is older than the TTL window.
        Caller owns the transaction and must commit.

        Args:
            domain: Filter rows to this domain only.
            ttl_minutes: Rows locked for longer than this interval are reset.

        Returns:
            Number of rows reset.

        Raises:
            RepositoryError: if the UPDATE fails.
        """
        try:
            stmt = text(
                """
                UPDATE sch_infra.scrape_queue
                   SET status    = 'PENDING',
                       locked_at = NULL
                 WHERE status    = 'IN_PROGRESS'
                   AND domain    = :domain
                   AND locked_at < now() - (:ttl * interval '1 minute')
                """
            )
            result = await self._session.execute(
                stmt, {"domain": domain, "ttl": ttl_minutes}
            )
            rowcount = cast(CursorResult, result).rowcount  # type: ignore[type-arg]
            assert rowcount is not None, "recover_stale: DML result has no rowcount"
            return rowcount
        except SQLAlchemyError as exc:
            raise RepositoryError(
                "recover_stale failed",
                operation="recover_stale",
                cause=exc,
            ) from exc

    async def mark_in_progress(self, row: ScrapeQueue) -> ScrapeQueue:
        """Transition *row* from PENDING to IN_PROGRESS.

        Sets locked_at to the current UTC time to enable stale detection.
        Flushes the change to the database but does NOT commit.
        The caller is responsible for committing the transaction.

        Args:
            row: The ScrapeQueue row to transition.

        Returns:
            The updated row.

        Raises:
            RepositoryError: if the flush fails.
        """
        try:
            row.status = ScrapeStatus.IN_PROGRESS
            row.locked_at = datetime.now(UTC)
            await self._session.flush()
            return row
        except SQLAlchemyError as exc:
            raise RepositoryError(
                "mark_in_progress failed",
                operation="mark_in_progress",
                cause=exc,
            ) from exc

    async def mark_done(self, row: ScrapeQueue) -> ScrapeQueue:
        """Transition *row* to DONE and record completion time.

        Clears locked_at (no longer in progress).
        Flushes but does NOT commit. Caller owns the transaction.

        Args:
            row: The ScrapeQueue row to mark as done.

        Returns:
            The updated row.

        Raises:
            RepositoryError: if the flush fails.
        """
        try:
            row.status = ScrapeStatus.DONE
            row.completed_at = datetime.now(UTC)
            row.locked_at = None
            await self._session.flush()
            return row
        except SQLAlchemyError as exc:
            raise RepositoryError(
                "mark_done failed",
                operation="mark_done",
                cause=exc,
            ) from exc

    async def mark_failed(
        self,
        row: ScrapeQueue,
        error: str,
        max_queue_retries: int,
    ) -> ScrapeStatus:
        """Transition *row* to FAILED (or re-queue as PENDING) based on retry ceiling.

        Increments retry_count and sets error_message unconditionally. Sets
        completed_at and terminal FAILED status only when the ceiling is reached;
        otherwise re-queues as PENDING. Caller owns the transaction.

        Args:
            row: The ScrapeQueue row to mark as failed.
            error: Human-readable description of the failure.
            max_queue_retries: Row becomes FAILED when retry_count reaches this ceiling.

        Returns:
            The new status of the row: PENDING (below ceiling) or FAILED (at/above).

        Raises:
            RepositoryError: if the flush fails.
        """
        try:
            row.retry_count += 1
            row.error_message = error
            row.locked_at = None

            if row.retry_count >= max_queue_retries:
                row.status = ScrapeStatus.FAILED
                row.completed_at = datetime.now(UTC)
            else:
                row.status = ScrapeStatus.PENDING

            await self._session.flush()
            return row.status
        except SQLAlchemyError as exc:
            raise RepositoryError(
                "mark_failed failed",
                operation="mark_failed",
                cause=exc,
            ) from exc
