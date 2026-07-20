"""Integration tests for ScrapeQueueRepository.recover_stale() and recover_all_stale().

Covers:
- recover_stale resets IN_PROGRESS rows older than the TTL to PENDING
- recover_stale does not reset recently-locked IN_PROGRESS rows
- recover_all_stale resets ALL IN_PROGRESS rows for the job_type unconditionally
- recover_all_stale does not touch IN_PROGRESS rows of a different job_type
- recover_all_stale returns 0 when there are no IN_PROGRESS rows
- mark_in_progress sets locked_at to a timezone-aware datetime

All tests use the async_session fixture (function-scoped, rolled back after each
test). No mocks — real Postgres via testcontainers.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.persistence.models.scrape_queue import ScrapeQueue, ScrapeStatus
from infrastructure.persistence.repositories.scrape_queue import (
    ScrapeQueueJobRepository as ScrapeQueueRepository,
)
from infrastructure.persistence.repositories.scrape_queue import (
    ScrapeQueueRepository as BaseQueueRepository,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DOMAIN = "fbref.com"
_TTL = 30  # minutes


async def _insert_in_progress(
    session: AsyncSession,
    url: str,
    *,
    locked_at: datetime,
) -> ScrapeQueue:
    """Insert a row already in IN_PROGRESS state with an explicit locked_at."""
    row = ScrapeQueue.from_url(url)
    row.status = ScrapeStatus.IN_PROGRESS
    row.locked_at = locked_at
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return row


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRecoverStale:
    async def test_recover_stale_resets_old_in_progress_rows(
        self, async_session: AsyncSession
    ) -> None:
        """IN_PROGRESS row with locked_at 31 min ago is reset to PENDING."""
        repo = ScrapeQueueRepository(async_session)
        old_locked_at = datetime.now(UTC) - timedelta(minutes=31)

        row = await _insert_in_progress(
            async_session,
            "https://fbref.com/en/players/stale/",
            locked_at=old_locked_at,
        )
        assert row.status == ScrapeStatus.IN_PROGRESS

        reset_count = await repo.recover_stale(_DOMAIN, _TTL)

        await async_session.refresh(row)
        assert reset_count >= 1
        assert row.status == ScrapeStatus.PENDING
        assert row.locked_at is None

    async def test_recover_stale_does_not_reset_recent_rows(
        self, async_session: AsyncSession
    ) -> None:
        """IN_PROGRESS row locked 5 minutes ago is not affected by recover_stale."""
        repo = ScrapeQueueRepository(async_session)
        recent_locked_at = datetime.now(UTC) - timedelta(minutes=5)

        row = await _insert_in_progress(
            async_session,
            "https://fbref.com/en/players/recent/",
            locked_at=recent_locked_at,
        )

        reset_count = await repo.recover_stale(_DOMAIN, _TTL)

        await async_session.refresh(row)
        assert reset_count == 0
        assert row.status == ScrapeStatus.IN_PROGRESS
        assert row.locked_at is not None


class TestMarkInProgressLockedAt:
    async def test_mark_in_progress_sets_locked_at(
        self, async_session: AsyncSession
    ) -> None:
        """mark_in_progress sets locked_at to a non-null, timezone-aware value."""
        repo = ScrapeQueueRepository(async_session)

        row = ScrapeQueue.from_url("https://fbref.com/en/players/new/")
        async_session.add(row)
        await async_session.flush()
        await async_session.refresh(row)

        assert row.locked_at is None

        await repo.mark_in_progress(row)

        assert row.locked_at is not None
        # locked_at must be timezone-aware (not naive)
        assert row.locked_at.tzinfo is not None


# ---------------------------------------------------------------------------
# Helpers for recover_all_stale tests
# ---------------------------------------------------------------------------

_JOB_TYPE = "player_list"
_OTHER_JOB_TYPE = "player_info"


async def _insert_in_progress_with_job_type(
    session: AsyncSession,
    url: str,
    *,
    job_type: str,
    locked_at: datetime | None = None,
) -> ScrapeQueue:
    """Insert a row already IN_PROGRESS for a given job_type."""
    row = ScrapeQueue(
        url=url,
        domain="fbref.com",
        status=ScrapeStatus.IN_PROGRESS,
        job_type=job_type,
        locked_at=locked_at or datetime.now(UTC),
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return row


# ---------------------------------------------------------------------------
# TestRecoverAllStale
# ---------------------------------------------------------------------------


class TestRecoverAllStale:
    async def test_resets_all_in_progress_rows_unconditionally(
        self, async_session: AsyncSession
    ) -> None:
        """recover_all_stale resets IN_PROGRESS rows regardless of lock age."""
        repo = BaseQueueRepository(async_session, job_type=_JOB_TYPE)

        # One row locked long ago, one locked just now
        old_row = await _insert_in_progress_with_job_type(
            async_session,
            "https://fbref.com/en/players/old/",
            job_type=_JOB_TYPE,
            locked_at=datetime.now(UTC) - timedelta(hours=2),
        )
        recent_row = await _insert_in_progress_with_job_type(
            async_session,
            "https://fbref.com/en/players/recent/",
            job_type=_JOB_TYPE,
            locked_at=datetime.now(UTC) - timedelta(seconds=5),
        )

        reset_count = await repo.recover_all_stale()

        await async_session.refresh(old_row)
        await async_session.refresh(recent_row)
        assert reset_count == 2
        assert old_row.status == ScrapeStatus.PENDING
        assert old_row.locked_at is None
        assert recent_row.status == ScrapeStatus.PENDING
        assert recent_row.locked_at is None

    async def test_does_not_touch_other_job_type(
        self, async_session: AsyncSession
    ) -> None:
        """recover_all_stale only resets rows matching its own job_type."""
        repo = BaseQueueRepository(async_session, job_type=_JOB_TYPE)

        other_row = await _insert_in_progress_with_job_type(
            async_session,
            "https://fbref.com/en/players/other/",
            job_type=_OTHER_JOB_TYPE,
        )

        reset_count = await repo.recover_all_stale()

        await async_session.refresh(other_row)
        assert reset_count == 0
        assert other_row.status == ScrapeStatus.IN_PROGRESS

    async def test_returns_zero_when_no_in_progress_rows(
        self, async_session: AsyncSession
    ) -> None:
        """recover_all_stale returns 0 when no IN_PROGRESS rows exist for job_type."""
        repo = BaseQueueRepository(async_session, job_type=_JOB_TYPE)

        reset_count = await repo.recover_all_stale()

        assert reset_count == 0
