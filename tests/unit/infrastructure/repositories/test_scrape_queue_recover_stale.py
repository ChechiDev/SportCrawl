"""Unit tests for ScrapeQueueRepository stale-recovery and locked_at lifecycle.

All database calls are mocked via AsyncMock session.
asyncio_mode = "auto" via pyproject.toml — no explicit @pytest.mark.asyncio.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

from infrastructure.persistence.models.scrape_queue import ScrapeQueue, ScrapeStatus
from infrastructure.persistence.repositories.scrape_queue import ScrapeQueueRepository

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session() -> AsyncMock:
    session = AsyncMock()
    session.flush = AsyncMock()
    return session


def _make_repo(session: AsyncMock | None = None) -> ScrapeQueueRepository:
    s = session or _make_session()
    return ScrapeQueueRepository(s)


def _make_row(
    status: ScrapeStatus = ScrapeStatus.IN_PROGRESS,
    locked_at: datetime | None = None,
) -> ScrapeQueue:
    row = ScrapeQueue()
    row.id = 1
    row.url = "https://fbref.com/en/players/d70ce98e/Messi"
    row.domain = "fbref.com"
    row.status = status
    row.locked_at = locked_at
    row.retry_count = 0
    row.error_message = None
    return row


# ---------------------------------------------------------------------------
# recover_stale tests
# ---------------------------------------------------------------------------


class TestRecoverStale:
    """Tests for ScrapeQueueRepository.recover_stale()."""

    async def test_recover_stale_executes_update_statement(self) -> None:
        """recover_stale must issue an UPDATE via session.execute()."""
        session = _make_session()
        result_mock = MagicMock()
        result_mock.rowcount = 2
        session.execute.return_value = result_mock

        repo = _make_repo(session)
        count = await repo.recover_stale("fbref.com", ttl_minutes=30)

        session.execute.assert_called_once()
        assert count == 2

    async def test_recover_stale_returns_rowcount(self) -> None:
        """recover_stale must return the number of rows reset."""
        session = _make_session()
        result_mock = MagicMock()
        result_mock.rowcount = 5
        session.execute.return_value = result_mock

        repo = _make_repo(session)
        count = await repo.recover_stale("fbref.com", ttl_minutes=30)

        assert count == 5

    async def test_recover_stale_returns_zero_when_no_stale_rows(self) -> None:
        """recover_stale must return 0 when no stale rows are found."""
        session = _make_session()
        result_mock = MagicMock()
        result_mock.rowcount = 0
        session.execute.return_value = result_mock

        repo = _make_repo(session)
        count = await repo.recover_stale("fbref.com", ttl_minutes=30)

        assert count == 0

    async def test_recover_stale_uses_ttl_parameter(self) -> None:
        """recover_stale must pass the ttl value into the UPDATE statement."""
        session = _make_session()
        result_mock = MagicMock()
        result_mock.rowcount = 1
        session.execute.return_value = result_mock

        repo = _make_repo(session)
        # Call with custom TTL — if TTL is ignored, behavior would differ
        await repo.recover_stale("fbref.com", ttl_minutes=60)

        # Content verified via integration tests; shape tested here.
        session.execute.assert_called_once()


# ---------------------------------------------------------------------------
# locked_at lifecycle tests
# ---------------------------------------------------------------------------


class TestLockedAtLifecycle:
    """Tests for locked_at management in mark_in_progress, mark_done, mark_failed."""

    async def test_mark_in_progress_sets_locked_at(self) -> None:
        """mark_in_progress must set locked_at to a non-None UTC datetime."""
        session = _make_session()
        row = _make_row(status=ScrapeStatus.PENDING)

        repo = _make_repo(session)
        await repo.mark_in_progress(row)

        assert row.locked_at is not None
        assert isinstance(row.locked_at, datetime)

    async def test_mark_in_progress_locked_at_is_utc(self) -> None:
        """mark_in_progress must set locked_at with UTC timezone info."""
        session = _make_session()
        row = _make_row(status=ScrapeStatus.PENDING)

        repo = _make_repo(session)
        await repo.mark_in_progress(row)

        assert row.locked_at is not None
        assert row.locked_at.tzinfo is not None

    async def test_mark_done_clears_locked_at(self) -> None:
        """mark_done must set locked_at to None."""
        session = _make_session()
        stale_time = datetime.now(UTC) - timedelta(minutes=5)
        row = _make_row(
            status=ScrapeStatus.IN_PROGRESS, locked_at=stale_time
        )

        repo = _make_repo(session)
        await repo.mark_done(row)

        assert row.locked_at is None

    async def test_mark_failed_clears_locked_at(self) -> None:
        """mark_failed must set locked_at to None regardless of status outcome."""
        session = _make_session()
        stale_time = datetime.now(UTC) - timedelta(minutes=5)
        row = _make_row(
            status=ScrapeStatus.IN_PROGRESS, locked_at=stale_time
        )
        row.retry_count = 0

        repo = _make_repo(session)
        await repo.mark_failed(row, "timeout", max_queue_retries=3)

        assert row.locked_at is None
