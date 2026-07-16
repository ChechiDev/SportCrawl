"""Integration tests for ScrapeQueueRepository.

Covers:
- list_pending: returns rows in insertion order, respects limit, excludes non-PENDING
- mark_in_progress: sets status=IN_PROGRESS, never commits
- mark_done: sets status=DONE, sets completed_at
- mark_failed: increments retry_count, sets error_message + completed_at
- mark_failed returns PENDING when below ceiling (retry_count < max_queue_retries)
- mark_failed returns FAILED when at/above ceiling (retry_count >= max_queue_retries)
- No method ever commits (session commit counter unchanged)

All tests use async_session from integration/conftest.py (rolled back after each test).
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.persistence.models.scrape_queue import ScrapeQueue, ScrapeStatus
from infrastructure.persistence.repositories.scrape_queue import ScrapeQueueJobRepository as ScrapeQueueRepository

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MAX_RETRIES = 3


async def _insert_pending(
    session: AsyncSession, url: str, *, retry_count: int = 0
) -> ScrapeQueue:
    """Insert a PENDING row and flush (no commit)."""
    row = ScrapeQueue.from_url(url)
    row.retry_count = retry_count
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return row


# ---------------------------------------------------------------------------
# list_pending
# ---------------------------------------------------------------------------


class TestListPending:
    async def test_returns_pending_rows_in_insertion_order(
        self, async_session: AsyncSession
    ) -> None:
        """list_pending returns PENDING rows ordered by id (insertion order)."""
        repo = ScrapeQueueRepository(async_session)
        urls = [
            "https://fbref.com/en/p1",
            "https://fbref.com/en/p2",
            "https://fbref.com/en/p3",
        ]
        inserted = [await _insert_pending(async_session, u) for u in urls]

        result = await repo.list_pending(limit=10)

        assert len(result) == 3
        assert [r.id for r in result] == [r.id for r in inserted]

    async def test_respects_limit(self, async_session: AsyncSession) -> None:
        """list_pending(limit=2) returns at most 2 rows even if more exist."""
        repo = ScrapeQueueRepository(async_session)
        for i in range(4):
            await _insert_pending(async_session, f"https://fbref.com/en/lim{i}")

        result = await repo.list_pending(limit=2)

        assert len(result) == 2

    async def test_excludes_non_pending_rows(self, async_session: AsyncSession) -> None:
        """list_pending does not return IN_PROGRESS or DONE rows."""
        repo = ScrapeQueueRepository(async_session)
        pending = await _insert_pending(async_session, "https://fbref.com/en/pending")
        in_prog = await _insert_pending(async_session, "https://fbref.com/en/in-prog")
        in_prog.status = ScrapeStatus.IN_PROGRESS
        await async_session.flush()

        result = await repo.list_pending(limit=10)

        ids = [r.id for r in result]
        assert pending.id in ids
        assert in_prog.id not in ids


# ---------------------------------------------------------------------------
# mark_in_progress
# ---------------------------------------------------------------------------


class TestMarkInProgress:
    async def test_sets_status_in_progress(self, async_session: AsyncSession) -> None:
        """mark_in_progress transitions a PENDING row to IN_PROGRESS."""
        repo = ScrapeQueueRepository(async_session)
        row = await _insert_pending(async_session, "https://fbref.com/en/mip1")

        await repo.mark_in_progress(row)

        assert row.status == ScrapeStatus.IN_PROGRESS

    async def test_does_not_commit(self, async_session: AsyncSession) -> None:
        """mark_in_progress never calls session.commit()."""
        repo = ScrapeQueueRepository(async_session)
        row = await _insert_pending(async_session, "https://fbref.com/en/mip2")

        # If the session were committed, in_transaction() would return False.
        assert async_session.in_transaction()
        await repo.mark_in_progress(row)
        assert async_session.in_transaction()


# ---------------------------------------------------------------------------
# mark_done
# ---------------------------------------------------------------------------


class TestMarkDone:
    async def test_sets_status_done(self, async_session: AsyncSession) -> None:
        """mark_done transitions a row to DONE and sets completed_at."""
        repo = ScrapeQueueRepository(async_session)
        row = await _insert_pending(async_session, "https://fbref.com/en/done1")
        await repo.mark_in_progress(row)

        await repo.mark_done(row)

        assert row.status == ScrapeStatus.DONE
        assert row.completed_at is not None

    async def test_completed_at_is_set(self, async_session: AsyncSession) -> None:
        """mark_done populates completed_at with a non-null timestamp."""
        repo = ScrapeQueueRepository(async_session)
        row = await _insert_pending(async_session, "https://fbref.com/en/done2")
        await repo.mark_in_progress(row)
        assert row.completed_at is None

        await repo.mark_done(row)

        assert row.completed_at is not None


# ---------------------------------------------------------------------------
# mark_failed
# ---------------------------------------------------------------------------


class TestMarkFailed:
    async def test_sets_status_failed_when_at_ceiling(
        self, async_session: AsyncSession
    ) -> None:
        """mark_failed sets status=FAILED when retry_count reaches max_queue_retries."""
        repo = ScrapeQueueRepository(async_session)
        # retry_count = max_queue_retries - 1; mark_failed increments → at ceiling
        row = await _insert_pending(
            async_session,
            "https://fbref.com/en/fail-ceil",
            retry_count=_MAX_RETRIES - 1,
        )
        await repo.mark_in_progress(row)

        new_status = await repo.mark_failed(row, "connection timeout", _MAX_RETRIES)

        assert new_status == ScrapeStatus.FAILED
        assert row.status == ScrapeStatus.FAILED

    async def test_increments_retry_count(self, async_session: AsyncSession) -> None:
        """mark_failed increments retry_count by 1."""
        repo = ScrapeQueueRepository(async_session)
        row = await _insert_pending(
            async_session,
            "https://fbref.com/en/retry-inc",
            retry_count=0,
        )
        await repo.mark_in_progress(row)

        await repo.mark_failed(row, "error", _MAX_RETRIES)

        assert row.retry_count == 1

    async def test_sets_error_message(self, async_session: AsyncSession) -> None:
        """mark_failed persists the error string on the row."""
        repo = ScrapeQueueRepository(async_session)
        row = await _insert_pending(async_session, "https://fbref.com/en/errmsg")
        await repo.mark_in_progress(row)

        await repo.mark_failed(row, "timeout after 30s", _MAX_RETRIES)

        assert row.error_message == "timeout after 30s"

    async def test_sets_completed_at(self, async_session: AsyncSession) -> None:
        """mark_failed sets completed_at only when the row reaches FAILED status."""
        repo = ScrapeQueueRepository(async_session)
        row = await _insert_pending(
            async_session,
            "https://fbref.com/en/comp-at",
            retry_count=_MAX_RETRIES - 1,  # hits ceiling → FAILED
        )
        await repo.mark_in_progress(row)

        await repo.mark_failed(row, "error", _MAX_RETRIES)

        assert row.status == ScrapeStatus.FAILED
        assert row.completed_at is not None

    async def test_returns_pending_when_below_ceiling(
        self, async_session: AsyncSession
    ) -> None:
        """mark_failed returns PENDING when retry_count < max_queue_retries."""
        repo = ScrapeQueueRepository(async_session)
        row = await _insert_pending(
            async_session,
            "https://fbref.com/en/below-ceil",
            retry_count=0,
        )
        await repo.mark_in_progress(row)

        new_status = await repo.mark_failed(row, "error", _MAX_RETRIES)

        assert new_status == ScrapeStatus.PENDING
        assert row.status == ScrapeStatus.PENDING

    async def test_returns_failed_at_ceiling(self, async_session: AsyncSession) -> None:
        """mark_failed returns FAILED when retry_count >= max_queue_retries."""
        repo = ScrapeQueueRepository(async_session)
        # Start at max-1; after increment → at ceiling → FAILED
        row = await _insert_pending(
            async_session,
            "https://fbref.com/en/at-ceil",
            retry_count=_MAX_RETRIES - 1,
        )
        await repo.mark_in_progress(row)

        returned = await repo.mark_failed(row, "error", _MAX_RETRIES)

        assert returned == ScrapeStatus.FAILED

    async def test_returns_failed_above_ceiling(
        self, async_session: AsyncSession
    ) -> None:
        """mark_failed returns FAILED when retry_count is already above ceiling."""
        repo = ScrapeQueueRepository(async_session)
        # Already over the ceiling
        row = await _insert_pending(
            async_session,
            "https://fbref.com/en/above-ceil",
            retry_count=_MAX_RETRIES + 1,
        )
        await repo.mark_in_progress(row)

        returned = await repo.mark_failed(row, "error", _MAX_RETRIES)

        assert returned == ScrapeStatus.FAILED
        assert row.status == ScrapeStatus.FAILED

    async def test_never_commits(self, async_session: AsyncSession) -> None:
        """mark_failed does not commit; changes are only flushed."""
        repo = ScrapeQueueRepository(async_session)
        row = await _insert_pending(async_session, "https://fbref.com/en/nocommit")
        await repo.mark_in_progress(row)

        # If commit were called, session.in_transaction() would become False.
        assert async_session.in_transaction()
        await repo.mark_failed(row, "error", _MAX_RETRIES)
        assert async_session.in_transaction()
