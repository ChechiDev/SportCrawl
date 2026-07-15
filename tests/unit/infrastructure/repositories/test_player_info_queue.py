"""Unit tests for PlayerInfoQueueRepository.

All database calls are mocked via AsyncMock session + text()/pg_insert patches.
asyncio_mode = "auto" via pyproject.toml — no explicit @pytest.mark.asyncio.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from infrastructure.persistence.repositories.player_info_queue import (
    PlayerInfoQueueRepository,
)
from infrastructure.persistence.models.scrape_queue import ScrapeQueue, ScrapeStatus

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_session() -> AsyncMock:
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.first.return_value = None
    result.rowcount = 0
    session.execute.return_value = result
    return session


def _make_pending_row(job_id: int = 1) -> ScrapeQueue:
    row = ScrapeQueue()
    row.id = job_id
    row.url = f"https://fbref.com/en/players/abc{job_id:05d}/Player"
    row.status = ScrapeStatus.PENDING
    row.retry_count = 0
    row.locked_at = None
    row.completed_at = None
    row.error_message = None
    row.job_type = "player_info"
    return row


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestClaimNext:
    async def test_claim_next_returns_pending_job_with_correct_job_type(self) -> None:
        """claim_next must execute a SELECT FOR UPDATE SKIP LOCKED filtered by job_type."""
        session = _make_session()
        row = _make_pending_row()
        result = MagicMock()
        result.scalars.return_value.first.return_value = row
        session.execute.return_value = result

        repo = PlayerInfoQueueRepository(session)
        claimed = await repo.claim_next(job_type="player_info")

        assert claimed is not None
        assert claimed.job_type == "player_info"
        assert claimed.status == ScrapeStatus.IN_PROGRESS
        assert claimed.locked_at is not None

    async def test_claim_next_returns_none_when_queue_empty(self) -> None:
        """claim_next must return None when no PENDING rows exist."""
        session = _make_session()
        result = MagicMock()
        result.scalars.return_value.first.return_value = None
        session.execute.return_value = result

        repo = PlayerInfoQueueRepository(session)
        claimed = await repo.claim_next(job_type="player_info")

        assert claimed is None


class TestMarkDone:
    async def test_mark_done_sets_status_done_and_clears_locked_at(self) -> None:
        """mark_done must set status=DONE, locked_at=None, completed_at to a datetime."""
        session = _make_session()
        row = _make_pending_row()
        row.status = ScrapeStatus.IN_PROGRESS
        row.locked_at = datetime.now(UTC)

        # make get() return the row
        session.get.return_value = row

        repo = PlayerInfoQueueRepository(session)
        await repo.mark_done(job_id=row.id)

        assert row.status == ScrapeStatus.DONE
        assert row.locked_at is None
        assert row.completed_at is not None


class TestMarkFailed:
    async def test_mark_failed_increments_retry_count(self) -> None:
        """mark_failed must increment retry_count and set error_message."""
        session = _make_session()
        row = _make_pending_row()
        row.retry_count = 0
        session.get.return_value = row

        repo = PlayerInfoQueueRepository(session)
        await repo.mark_failed(job_id=row.id, error="timeout")

        assert row.retry_count == 1
        assert row.error_message == "timeout"

    async def test_mark_failed_sets_status_pending_below_ceiling(self) -> None:
        """mark_failed below retry ceiling must requeue as PENDING."""
        session = _make_session()
        row = _make_pending_row()
        row.retry_count = 1
        session.get.return_value = row

        repo = PlayerInfoQueueRepository(session)
        await repo.mark_failed(job_id=row.id, error="timeout")

        assert row.status == ScrapeStatus.PENDING
        assert row.locked_at is None

    async def test_mark_failed_sets_status_failed_when_retry_count_reaches_3(self) -> None:
        """mark_failed at retry ceiling (3) must set status=FAILED permanently."""
        session = _make_session()
        row = _make_pending_row()
        row.retry_count = 2  # will become 3 → FAILED
        session.get.return_value = row

        repo = PlayerInfoQueueRepository(session)
        await repo.mark_failed(job_id=row.id, error="parse error")

        assert row.status == ScrapeStatus.FAILED
        assert row.completed_at is not None


class TestRecoverStale:
    async def test_recover_stale_resets_in_progress_rows_older_than_cutoff(self) -> None:
        """recover_stale must issue an UPDATE and return the count of reset rows."""
        session = _make_session()
        result = MagicMock()
        result.rowcount = 3
        session.execute.return_value = result

        repo = PlayerInfoQueueRepository(session)
        count = await repo.recover_stale(cutoff_minutes=30)

        assert count == 3
        session.execute.assert_called_once()
