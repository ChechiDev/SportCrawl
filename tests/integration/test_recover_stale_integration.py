"""Integration tests for ScrapeQueueRepository.recover_stale().

Covers:
- recover_stale resets IN_PROGRESS rows older than the TTL to PENDING
- recover_stale does not reset recently-locked IN_PROGRESS rows
- mark_in_progress sets locked_at to a timezone-aware datetime

All tests use the async_session fixture (function-scoped, rolled back after each
test). No mocks — real Postgres via testcontainers.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.persistence.models.scrape_queue import ScrapeQueue, ScrapeStatus
from infrastructure.persistence.repositories.scrape_queue import ScrapeQueueRepository

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
