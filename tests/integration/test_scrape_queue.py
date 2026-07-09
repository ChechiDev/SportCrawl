"""Integration tests for the ScrapeQueue ORM model.

Covers R8 (CRUD + upsert), R9 (status transitions), R13 (testcontainers Postgres).

Schema is created once per session via the autouse ``migrate_db`` fixture in
``tests/integration/conftest.py``.  Each test function receives a fresh
``async_session`` (function-scoped, rolled back after each test).
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.persistence.models.scrape_queue import ScrapeQueue, ScrapeStatus

# ---------------------------------------------------------------------------
# CRUD Tests
# ---------------------------------------------------------------------------


class TestScrapeQueueCreate:
    """Verify that a ScrapeQueue row can be inserted and retrieved."""

    async def test_create_row_persists(self, async_session: AsyncSession) -> None:
        """A new ScrapeQueue row inserted via ORM is readable in the same session."""
        row = ScrapeQueue.from_url(
            domain="example.com", url="https://example.com/page1"
        )
        async_session.add(row)
        await async_session.flush()

        assert row.id is not None
        assert row.status == ScrapeStatus.PENDING
        assert row.retry_count == 0
        assert row.completed_at is None
        assert row.error_message is None

    async def test_created_at_is_set(self, async_session: AsyncSession) -> None:
        """created_at is populated by the server default on insert."""
        row = ScrapeQueue.from_url(
            domain="example.com", url="https://example.com/page2"
        )
        async_session.add(row)
        await async_session.flush()
        await async_session.refresh(row)

        assert row.created_at is not None
        assert isinstance(row.created_at, datetime)


# ---------------------------------------------------------------------------
# Get Tests
# ---------------------------------------------------------------------------


class TestScrapeQueueGet:
    """Verify that a persisted row can be fetched by primary key and filtered."""

    async def test_get_by_primary_key(self, async_session: AsyncSession) -> None:
        """A flushed row is retrievable via session.get()."""
        row = ScrapeQueue.from_url(domain="example.com", url="https://example.com/get1")
        async_session.add(row)
        await async_session.flush()

        fetched = await async_session.get(ScrapeQueue, row.id)
        assert fetched is not None
        assert fetched.url == "https://example.com/get1"
        assert fetched.domain == "example.com"

    async def test_get_nonexistent_returns_none(
        self, async_session: AsyncSession
    ) -> None:
        """session.get() returns None for a primary key that does not exist."""
        result = await async_session.get(ScrapeQueue, 999_999)
        assert result is None


# ---------------------------------------------------------------------------
# List Tests
# ---------------------------------------------------------------------------


class TestScrapeQueueList:
    """Verify SELECT queries with status filters work correctly."""

    async def test_list_by_status(self, async_session: AsyncSession) -> None:
        """SELECT filtered by status returns only matching rows."""
        pending = ScrapeQueue.from_url(
            domain="list.com", url="https://list.com/pending"
        )
        async_session.add(pending)
        await async_session.flush()

        stmt = select(ScrapeQueue).where(ScrapeQueue.status == ScrapeStatus.PENDING)
        result = await async_session.execute(stmt)
        rows = result.scalars().all()

        assert len(rows) == 1
        assert all(r.status == ScrapeStatus.PENDING for r in rows)

    async def test_list_by_domain(self, async_session: AsyncSession) -> None:
        """SELECT filtered by domain returns only matching rows."""
        row = ScrapeQueue.from_url(
            domain="specific-domain.io", url="https://specific-domain.io/path"
        )
        async_session.add(row)
        await async_session.flush()

        stmt = select(ScrapeQueue).where(ScrapeQueue.domain == "specific-domain.io")
        result = await async_session.execute(stmt)
        rows = result.scalars().all()

        assert len(rows) == 1
        assert all(r.domain == "specific-domain.io" for r in rows)


# ---------------------------------------------------------------------------
# Delete Tests
# ---------------------------------------------------------------------------


class TestScrapeQueueDelete:
    """Verify that a row can be deleted by primary key."""

    async def test_delete_row(self, async_session: AsyncSession) -> None:
        """A flushed row deleted via session.delete() is no longer retrievable."""
        row = ScrapeQueue.from_url(domain="del.com", url="https://del.com/remove")
        async_session.add(row)
        await async_session.flush()
        row_id = row.id

        await async_session.delete(row)
        await async_session.flush()

        fetched = await async_session.get(ScrapeQueue, row_id)
        assert fetched is None


# ---------------------------------------------------------------------------
# Upsert Tests (R8)
# ---------------------------------------------------------------------------


class TestScrapeQueueUpsert:
    """Verify INSERT ... ON CONFLICT DO UPDATE semantics (R8).

    The unique constraint on ``url`` means a duplicate insert must update
    the existing row rather than create a new one.
    """

    async def test_upsert_does_not_create_duplicate(
        self, async_session: AsyncSession
    ) -> None:
        """Inserting the same URL twice via ON CONFLICT UPDATE leaves one row."""
        url = "https://upsert.com/target"
        domain = "upsert.com"

        stmt = (
            pg_insert(ScrapeQueue)
            .values(url=url, domain=domain, status=ScrapeStatus.PENDING)
            .on_conflict_do_update(
                constraint="uq_scrape_queue_url",
                set_={"retry_count": ScrapeQueue.retry_count + 1},
            )
        )
        await async_session.execute(stmt)
        await async_session.flush()

        # Second insert with same URL — must update, not insert.
        await async_session.execute(stmt)
        await async_session.flush()

        count_result = await async_session.execute(
            select(ScrapeQueue).where(ScrapeQueue.url == url)
        )
        rows = count_result.scalars().all()

        assert len(rows) == 1

    async def test_upsert_updates_retry_count(
        self, async_session: AsyncSession
    ) -> None:
        """After a duplicate insert, retry_count is incremented on the existing row."""
        url = "https://upsert.com/retry-count"
        domain = "upsert.com"

        stmt = (
            pg_insert(ScrapeQueue)
            .values(url=url, domain=domain, status=ScrapeStatus.PENDING)
            .on_conflict_do_update(
                constraint="uq_scrape_queue_url",
                set_={"retry_count": ScrapeQueue.retry_count + 1},
            )
        )
        await async_session.execute(stmt)
        await async_session.flush()
        await async_session.execute(stmt)
        await async_session.flush()

        result = await async_session.execute(
            select(ScrapeQueue).where(ScrapeQueue.url == url)
        )
        row = result.scalar_one()
        assert row.retry_count == 1

    async def test_unique_constraint_blocks_plain_duplicate_insert(
        self, async_session: AsyncSession
    ) -> None:
        """Plain INSERT of a duplicate URL raises IntegrityError (no ON CONFLICT)."""
        url = "https://upsert.com/plain-dup"
        row1 = ScrapeQueue.from_url(domain="upsert.com", url=url)
        row2 = ScrapeQueue.from_url(domain="upsert.com", url=url)

        async_session.add(row1)
        await async_session.flush()

        async_session.add(row2)
        with pytest.raises(IntegrityError):
            await async_session.flush()


# ---------------------------------------------------------------------------
# Status Transition Tests (R9)
# ---------------------------------------------------------------------------


class TestScrapeQueueStatusTransitions:
    """Verify valid status transitions as defined in R9.

    Valid paths:
      pending → in_progress → done
      pending → in_progress → failed
      failed  → pending  (retry path only)
    """

    async def test_pending_to_in_progress(self, async_session: AsyncSession) -> None:
        """A row can transition from PENDING to IN_PROGRESS."""
        row = ScrapeQueue.from_url(
            domain="transitions.com", url="https://transitions.com/t1"
        )
        async_session.add(row)
        await async_session.flush()
        assert row.status == ScrapeStatus.PENDING

        row.status = ScrapeStatus.IN_PROGRESS
        await async_session.flush()
        await async_session.refresh(row)

        assert row.status == ScrapeStatus.IN_PROGRESS

    async def test_in_progress_to_done(self, async_session: AsyncSession) -> None:
        """A row can transition from IN_PROGRESS to DONE."""
        row = ScrapeQueue.from_url(
            domain="transitions.com", url="https://transitions.com/t2"
        )
        async_session.add(row)
        await async_session.flush()
        row.status = ScrapeStatus.IN_PROGRESS
        await async_session.flush()

        row.status = ScrapeStatus.DONE
        row.completed_at = datetime.now(tz=UTC)
        await async_session.flush()
        await async_session.refresh(row)

        assert row.status == ScrapeStatus.DONE
        assert row.completed_at is not None

    async def test_in_progress_to_failed(self, async_session: AsyncSession) -> None:
        """A row can transition from IN_PROGRESS to FAILED with an error message."""
        row = ScrapeQueue.from_url(
            domain="transitions.com", url="https://transitions.com/t3"
        )
        async_session.add(row)
        await async_session.flush()
        row.status = ScrapeStatus.IN_PROGRESS
        await async_session.flush()

        row.status = ScrapeStatus.FAILED
        row.error_message = "Connection timeout"
        row.completed_at = datetime.now(tz=UTC)
        await async_session.flush()
        await async_session.refresh(row)

        assert row.status == ScrapeStatus.FAILED
        assert row.error_message == "Connection timeout"

    async def test_failed_to_pending_retry_path(
        self, async_session: AsyncSession
    ) -> None:
        """A FAILED row can re-enter the queue as PENDING via the retry path (R9)."""
        row = ScrapeQueue.from_url(
            domain="transitions.com", url="https://transitions.com/t4"
        )
        async_session.add(row)
        await async_session.flush()
        row.status = ScrapeStatus.IN_PROGRESS
        await async_session.flush()
        row.status = ScrapeStatus.FAILED
        row.error_message = "Timeout"
        await async_session.flush()

        # Retry path: reset to pending, clear error, increment retry count.
        row.status = ScrapeStatus.PENDING
        row.error_message = None
        row.retry_count += 1
        await async_session.flush()
        await async_session.refresh(row)

        assert row.status == ScrapeStatus.PENDING
        assert row.retry_count == 1
        assert row.error_message is None

    async def test_failed_row_appears_in_pending_query(
        self, async_session: AsyncSession
    ) -> None:
        """After the retry path, the row is returned by a PENDING status query."""
        row = ScrapeQueue.from_url(
            domain="transitions.com", url="https://transitions.com/t5"
        )
        async_session.add(row)
        await async_session.flush()
        row.status = ScrapeStatus.FAILED
        await async_session.flush()

        # Simulate retry.
        row.status = ScrapeStatus.PENDING
        row.retry_count += 1
        await async_session.flush()

        stmt = select(ScrapeQueue).where(
            ScrapeQueue.url == "https://transitions.com/t5",
            ScrapeQueue.status == ScrapeStatus.PENDING,
        )
        result = await async_session.execute(stmt)
        fetched = result.scalar_one_or_none()

        assert fetched is not None
        assert fetched.status == ScrapeStatus.PENDING
