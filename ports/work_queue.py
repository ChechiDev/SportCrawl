"""WorkQueuePort — pure structural Protocol for work-queue coordination.

Defines the contract between the HTTP work server and the persistence adapter.
No SQLAlchemy or infrastructure imports are permitted here (import-linter enforced).

REQ-9.5: The protocol must be declared in ports/, must not reference any concrete
persistence class, and must be satisfiable by both a real adapter and a test double.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class JobRecordProtocol(Protocol):
    """Structural protocol for a job record returned by WorkQueuePort operations.

    Any object with the three attributes below satisfies this protocol — ORM rows,
    plain dataclasses, and test doubles all qualify without inheriting from this class.
    """

    id: int
    url: str
    status: str  # "PENDING" | "IN_PROGRESS" | "DONE" | "FAILED"


@runtime_checkable
class WorkQueuePort(Protocol):
    """Async port for work-queue coordination.

    Implemented by ScrapeQueueWorkAdapter (infrastructure.persistence.adapters).
    Depended on by the aiohttp handlers (infrastructure.work_server).
    Test doubles may implement this protocol without inheriting from it.

    Methods:
        enqueue: Insert a new PENDING job for the given URL.
                 Raises DuplicateError if the URL already exists in the queue.
        get_job: Return the current record for the given job ID, or None if absent.
    """

    async def enqueue(self, url: str) -> JobRecordProtocol:
        """Enqueue a URL for scraping.

        Args:
            url: The target URL to scrape. Must pass SSRF validation.

        Returns:
            A JobRecordProtocol-compatible record with status PENDING.

        Raises:
            DuplicateError: if the URL is already present in the queue.
            SSRFError: if the URL fails SSRF validation.
        """
        ...

    async def get_job(self, job_id: int) -> JobRecordProtocol | None:
        """Return the current record for a job, or None if absent.

        Args:
            job_id: The integer primary key of the scrape_queue row.

        Returns:
            A JobRecordProtocol-compatible record, or None if not found.
        """
        ...
