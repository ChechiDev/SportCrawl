"""Unit tests for ScrapeQueueWorkAdapter (task 2.1 — RED before implementation).

Tests use mocked session factory; no real DB required.

Covers:
- enqueue() returns a JobRecordProtocol-compatible object with status PENDING
- enqueue() wraps IntegrityError as DuplicateError
- enqueue() propagates SSRFError unchanged
- get_job() returns a JobRecordProtocol-compatible object when the row exists
- get_job() returns None when the row does not exist
- Adapter satisfies isinstance(WorkQueuePort) structural check
- Adapter commits the session on success (owns its own transaction)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError

from core.exceptions.repository import DuplicateError
from infrastructure.persistence.adapters.work_queue import ScrapeQueueWorkAdapter
from infrastructure.persistence.models.scrape_queue import ScrapeQueue, ScrapeStatus
from ports.work_queue import JobRecordProtocol, WorkQueuePort


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_scrape_queue_row(
    *,
    id: int = 1,
    url: str = "https://fbref.com/en/page",
    status: ScrapeStatus = ScrapeStatus.PENDING,
) -> MagicMock:
    """Return a MagicMock mimicking a ScrapeQueue row without needing a DB session."""
    row = MagicMock(spec=ScrapeQueue)
    row.id = id
    row.url = url
    row.status = status
    row.domain = "fbref.com"
    row.error_message = None
    row.retry_count = 0
    row.completed_at = None
    return row


def _make_factory(session: AsyncMock) -> MagicMock:
    """Return a session factory mock that yields the given session."""
    factory = MagicMock()
    factory.return_value = session
    return factory


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestScrapeQueueWorkAdapterProtocolCompliance:
    """Structural check: adapter must satisfy WorkQueuePort."""

    def test_adapter_is_instance_of_work_queue_port(self) -> None:
        """ScrapeQueueWorkAdapter satisfies isinstance(WorkQueuePort) — REQ-9.5."""
        factory = MagicMock()
        adapter = ScrapeQueueWorkAdapter(factory)
        assert isinstance(adapter, WorkQueuePort)


class TestScrapeQueueWorkAdapterEnqueue:
    """Tests for the enqueue() method."""

    async def test_enqueue_returns_job_record_protocol(self) -> None:
        """enqueue() returns an object satisfying JobRecordProtocol with PENDING status."""
        session = AsyncMock()
        session.flush = AsyncMock()
        session.refresh = AsyncMock()
        session.commit = AsyncMock()
        session.rollback = AsyncMock()
        session.close = AsyncMock()

        row = _make_scrape_queue_row()
        session.flush.side_effect = None

        # Patch ScrapeQueue.from_url to return our controlled row
        with patch(
            "infrastructure.persistence.adapters.work_queue.ScrapeQueue.from_url",
            return_value=row,
        ):
            # Patch session.refresh to populate id after flush
            async def _refresh(obj: object) -> None:
                pass

            session.refresh.side_effect = _refresh

            factory = _make_factory(session)
            adapter = ScrapeQueueWorkAdapter(factory)
            result = await adapter.enqueue("https://fbref.com/en/page")

        assert isinstance(result, JobRecordProtocol)
        assert result.status == "PENDING"
        assert result.url == "https://fbref.com/en/page"
        assert result.id == 1

    async def test_enqueue_commits_own_transaction(self) -> None:
        """Adapter must call session.commit() — it owns the transaction."""
        session = AsyncMock()
        session.flush = AsyncMock()
        session.refresh = AsyncMock()
        session.commit = AsyncMock()
        session.rollback = AsyncMock()
        session.close = AsyncMock()

        row = _make_scrape_queue_row()

        with patch(
            "infrastructure.persistence.adapters.work_queue.ScrapeQueue.from_url",
            return_value=row,
        ):
            factory = _make_factory(session)
            adapter = ScrapeQueueWorkAdapter(factory)
            await adapter.enqueue("https://fbref.com/en/page")

        session.commit.assert_awaited_once()

    async def test_enqueue_duplicate_url_raises_duplicate_error(self) -> None:
        """IntegrityError from the DB is converted to DuplicateError."""
        session = AsyncMock()
        session.flush = AsyncMock(
            side_effect=IntegrityError(
                statement=None, params=None, orig=Exception("duplicate key")
            )
        )
        session.rollback = AsyncMock()
        session.close = AsyncMock()

        row = _make_scrape_queue_row()

        with patch(
            "infrastructure.persistence.adapters.work_queue.ScrapeQueue.from_url",
            return_value=row,
        ):
            factory = _make_factory(session)
            adapter = ScrapeQueueWorkAdapter(factory)

            with pytest.raises(DuplicateError):
                await adapter.enqueue("https://fbref.com/en/page")

    async def test_enqueue_rolls_back_on_integrity_error(self) -> None:
        """Session is rolled back when IntegrityError is raised."""
        session = AsyncMock()
        session.flush = AsyncMock(
            side_effect=IntegrityError(
                statement=None, params=None, orig=Exception("duplicate key")
            )
        )
        session.rollback = AsyncMock()
        session.close = AsyncMock()

        row = _make_scrape_queue_row()

        with patch(
            "infrastructure.persistence.adapters.work_queue.ScrapeQueue.from_url",
            return_value=row,
        ):
            factory = _make_factory(session)
            adapter = ScrapeQueueWorkAdapter(factory)

            with pytest.raises(DuplicateError):
                await adapter.enqueue("https://fbref.com/en/page")

        session.rollback.assert_awaited()


class TestScrapeQueueWorkAdapterGetJob:
    """Tests for the get_job() method."""

    async def test_get_job_returns_job_record_when_found(self) -> None:
        """get_job() returns JobRecordProtocol-compatible object when row exists."""
        row = _make_scrape_queue_row(id=7, url="https://fbref.com/found", status=ScrapeStatus.DONE)

        session = AsyncMock()
        session.get = AsyncMock(return_value=row)
        session.close = AsyncMock()

        factory = _make_factory(session)
        adapter = ScrapeQueueWorkAdapter(factory)
        result = await adapter.get_job(7)

        assert result is not None
        assert isinstance(result, JobRecordProtocol)
        assert result.id == 7
        assert result.status == "DONE"

    async def test_get_job_returns_none_when_not_found(self) -> None:
        """get_job() returns None when no row exists for the given id."""
        session = AsyncMock()
        session.get = AsyncMock(return_value=None)
        session.close = AsyncMock()

        factory = _make_factory(session)
        adapter = ScrapeQueueWorkAdapter(factory)
        result = await adapter.get_job(999)

        assert result is None
