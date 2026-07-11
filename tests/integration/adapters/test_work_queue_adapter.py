"""Integration tests for ScrapeQueueWorkAdapter against a real Postgres container.

Uses the session-scoped testcontainer fixtures from tests/integration/conftest.py.
The adapter is exercised through its WorkQueuePort interface.

Isolation strategy: each test uses a unique URL suffix (UUID4-keyed) so rows do
not interfere with other integration tests. The adapter_session fixture truncates
the sch_infra.scrape_queue table after each test so count-based assertions in
other test modules are not affected.

Covers (tasks 2.3–2.4):
- enqueue() creates a PENDING row in the database
- get_job() returns the row with its current status
- Duplicate URL raises DuplicateError
- get_job() for a non-existent id returns None
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.engine.url import URL
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.exceptions.repository import DuplicateError
from infrastructure.persistence.adapters.work_queue import ScrapeQueueWorkAdapter
from ports.work_queue import JobRecordProtocol

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(loop_scope="function")
async def _adapter_engine(_integration_db_url: URL):
    """Create a fresh async engine per test and dispose it after."""
    engine = create_async_engine(_integration_db_url, echo=False)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(loop_scope="function")
async def adapter(_adapter_engine) -> ScrapeQueueWorkAdapter:
    """Return a ScrapeQueueWorkAdapter backed by the testcontainer Postgres.

    Cleans up all rows inserted during the test so count-based assertions
    in parallel test modules are not contaminated.
    """
    factory = async_sessionmaker(_adapter_engine, expire_on_commit=False)
    yield ScrapeQueueWorkAdapter(factory)

    # Cleanup: delete all rows inserted during this test
    async with _adapter_engine.connect() as conn:
        await conn.execute(text("DELETE FROM sch_infra.scrape_queue"))
        await conn.commit()


def _unique_url(suffix: str = "") -> str:
    """Generate a unique fbref.com URL for test isolation."""
    return f"https://fbref.com/adapter-integration/{uuid.uuid4().hex}/{suffix}"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestScrapeQueueWorkAdapterIntegration:
    """Integration tests: real DB, real adapter, no mocks."""

    async def test_enqueue_creates_pending_row(
        self, adapter: ScrapeQueueWorkAdapter
    ) -> None:
        """enqueue() persists a PENDING row that is retrievable via get_job()."""
        url = _unique_url("enqueue-creates-pending")
        record = await adapter.enqueue(url)

        assert isinstance(record, JobRecordProtocol)
        assert record.url == url
        assert record.status == "PENDING"
        assert record.id is not None

    async def test_get_job_returns_enqueued_row(
        self, adapter: ScrapeQueueWorkAdapter
    ) -> None:
        """get_job() retrieves the row created by a previous enqueue() call."""
        url = _unique_url("get-job-returns")
        enqueued = await adapter.enqueue(url)

        fetched = await adapter.get_job(enqueued.id)

        assert fetched is not None
        assert isinstance(fetched, JobRecordProtocol)
        assert fetched.id == enqueued.id
        assert fetched.url == url
        assert fetched.status == "PENDING"

    async def test_enqueue_duplicate_url_raises_duplicate_error(
        self, adapter: ScrapeQueueWorkAdapter
    ) -> None:
        """Enqueuing the same URL twice raises DuplicateError on the second call."""
        url = _unique_url("duplicate-url")
        await adapter.enqueue(url)

        with pytest.raises(DuplicateError):
            await adapter.enqueue(url)

    async def test_get_job_nonexistent_returns_none(
        self, adapter: ScrapeQueueWorkAdapter
    ) -> None:
        """get_job() returns None when no row with the given id exists."""
        result = await adapter.get_job(999_999_999)
        assert result is None
