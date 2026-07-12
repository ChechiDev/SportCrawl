"""ScrapeQueueRepository — async state-machine repository for the scrape_queue table.

Encodes the PENDING → IN_PROGRESS → DONE | FAILED lifecycle as explicit transition
methods. The caller (JobLoop) owns the transaction; this repository never commits.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from sqlalchemy import select, text
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import SQLAlchemyError

from core.exceptions.repository import RepositoryError
from infrastructure.persistence.models.scrape_queue import ScrapeQueue, ScrapeStatus
from ports.repository import BaseRepository


class ScrapeQueueRepository(BaseRepository[ScrapeQueue]):
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
