"""ScrapeQueueWorkAdapter — WorkQueuePort implementation backed by scrape_queue table.

Unlike ScrapeQueueRepository (which never commits and returns ORM rows), this adapter:
- Owns its own transaction (commits on success, rolls back on error).
- Maps ORM rows to plain JobRecord dataclasses so no SQLAlchemy state leaks into ports.
- Converts IntegrityError (uq_scrape_queue_url) into DuplicateError.

Session lifecycle: a new session is opened per call (short-lived request transaction).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.exceptions.repository import DuplicateError
from infrastructure.persistence.models.scrape_queue import ScrapeQueue
from ports.work_queue import JobRecordProtocol


@dataclass
class JobRecord:
    """Plain dataclass satisfying JobRecordProtocol.

    Returned by ScrapeQueueWorkAdapter to ensure no ORM state leaks across the
    port boundary.
    """

    id: int
    url: str
    status: str  # "PENDING" | "IN_PROGRESS" | "DONE" | "FAILED"


def _row_to_record(row: ScrapeQueue) -> JobRecord:
    """Convert a ScrapeQueue ORM row to a plain JobRecord."""
    return JobRecord(
        id=row.id,
        url=row.url,
        status=row.status.name,  # ScrapeStatus.PENDING.name == "PENDING"
    )


class ScrapeQueueWorkAdapter:
    """WorkQueuePort adapter backed by the scrape_queue table.

    Accepts a SQLAlchemy async_sessionmaker and manages short-lived per-call
    transactions. The session is committed on success and rolled back on error.

    Usage:
        factory = create_session_factory(settings.db)
        adapter = ScrapeQueueWorkAdapter(factory)
        record = await adapter.enqueue("https://fbref.com/...")
    """

    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    async def enqueue(self, url: str) -> JobRecordProtocol:
        """Enqueue a URL as a new PENDING scrape_queue row.

        Validates the URL via ScrapeQueue.from_url (SSRF + domain derivation).
        Commits the session on success; rolls back and raises DuplicateError
        if the URL already exists (uq_scrape_queue_url constraint violation).

        Args:
            url: The target URL to scrape. Must use HTTPS and pass SSRF allowlist.

        Returns:
            A JobRecord with the new row's id, url, and status="PENDING".

        Raises:
            DuplicateError: if the URL is already present in scrape_queue.
            SSRFError: if the URL fails scheme/allowlist/private-IP checks.
        """
        session: AsyncSession = self._factory()
        try:
            row = ScrapeQueue.from_url(url)
            session.add(row)
            await session.flush()
            await session.refresh(row)
            record = _row_to_record(row)
            await session.commit()
            return record
        except IntegrityError as exc:
            await session.rollback()
            raise DuplicateError(
                f"URL already exists in scrape_queue: {url}",
                cause=exc,
            ) from exc
        except BaseException:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def get_job(self, job_id: int) -> JobRecordProtocol | None:
        """Return the current record for a job, or None if absent.

        Opens a short read-only session. No transaction commit is required
        for a plain SELECT.

        Args:
            job_id: The integer primary key of the scrape_queue row.

        Returns:
            A JobRecord with the row's current state, or None if not found.
        """
        session: AsyncSession = self._factory()
        try:
            row = await session.get(ScrapeQueue, job_id)
            if row is None:
                return None
            return _row_to_record(row)
        finally:
            await session.close()
