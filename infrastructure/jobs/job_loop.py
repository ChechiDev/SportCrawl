"""JobLoop — semaphore-gated async batch orchestrator.

Drains PENDING rows from the scrape_queue concurrently, hashes raw HTML
into Provenance records, and manages the per-job transaction lifecycle.

Design decisions (Phase 5):
- JobLoop calls scraper.fetch_and_parse(url), then reads scraper.last_html
  for the SHA256 content_hash. The scraper owns fetch + retry internally.
- mark_failed(row, error, max_queue_retries) owns retry-ceiling evaluation and
  returns the new status. JobLoop reads the returned status — no ceiling logic here.
- FAILED is terminal; re-queue only when mark_failed returns PENDING.
- One session per job — transaction-per-job isolates failures.
- asyncio.gather(..., return_exceptions=True) ensures one crashing coroutine
  cannot abort sibling jobs.

Independence contract:
- All infrastructure.persistence types flow through injected factories/protocols.
  JobLoop only imports from ports, config, and stdlib — never from
  infrastructure.persistence or infrastructure.browser directly.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Any, Protocol

from config.settings import ScrapingSettings
from core.exceptions.repository import RepositoryError
from core.exceptions.scraper import ScraperError
from ports.scraper import BaseScraper

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Protocols — infrastructure.persistence boundary
# ---------------------------------------------------------------------------


class _Session(Protocol):
    """Minimal session contract — keeps infrastructure.jobs free of SQLAlchemy."""

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class ScrapeQueueRowProtocol(Protocol):
    """Minimal structural contract for a scrape-queue row.

    JobLoop only accesses these fields — no ORM model is imported directly.
    """

    id: int
    url: str
    retry_count: int


class _QueueRepo(Protocol):
    """Protocol for ScrapeQueueRepository methods used by JobLoop."""

    async def get(self, id: int) -> ScrapeQueueRowProtocol | None: ...  # noqa: A002

    async def list_pending(self, limit: int) -> list[ScrapeQueueRowProtocol]: ...

    async def mark_in_progress(
        self, row: ScrapeQueueRowProtocol
    ) -> ScrapeQueueRowProtocol: ...

    async def mark_done(
        self, row: ScrapeQueueRowProtocol
    ) -> ScrapeQueueRowProtocol: ...

    async def mark_failed(
        self,
        row: ScrapeQueueRowProtocol,
        error: str,
        max_queue_retries: int,
    ) -> Any: ...


class _ProvRepo(Protocol):
    """Protocol for ProvenanceRepository methods used by JobLoop."""

    async def create(self, entity: Any) -> Any: ...


# ---------------------------------------------------------------------------
# Factory type aliases
# ---------------------------------------------------------------------------

SessionFactory = Callable[[], AbstractAsyncContextManager[_Session]]
ScraperFactory = Callable[[str], BaseScraper[Any]]
QueueRepoFactory = Callable[[_Session], _QueueRepo]
ProvenanceRepoFactory = Callable[[_Session], _ProvRepo]

# Builds a Provenance-like row: (url, outcome_str, content_hash, run_id).
# Injected so JobLoop never imports infrastructure.persistence.models.
ProvenanceFactory = Callable[[str, str, str, uuid.UUID], Any]


class JobLoop:
    """Concurrent batch runner for the scrape_queue.

    All dependencies are injected at construction time. No concrete adapter
    types are imported directly — this keeps the independence contract intact.

    Constructor args:
        session_factory: Returns an async context manager yielding an AsyncSession.
        scraper_factory: Returns a BaseScraper instance for a given URL.
        queue_repo_factory: Returns a _QueueRepo bound to a session.
        provenance_repo_factory: Returns a _ProvRepo bound to a session.
        provenance_factory: Callable(url, outcome_str, content_hash, run_id).
        settings: ScrapingSettings supplying concurrency and retry limits.
    """

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        scraper_factory: ScraperFactory,
        queue_repo_factory: QueueRepoFactory,
        provenance_repo_factory: ProvenanceRepoFactory,
        provenance_factory: ProvenanceFactory,
        settings: ScrapingSettings,
    ) -> None:
        self._session_factory = session_factory
        self._scraper_factory = scraper_factory
        self._queue_repo_factory = queue_repo_factory
        self._provenance_repo_factory = provenance_repo_factory
        self._provenance_factory = provenance_factory
        self._settings = settings

    async def drain(
        self,
        *,
        batch_size: int,
        stop_event: asyncio.Event,
    ) -> int:
        """Process all PENDING jobs until the queue is empty or stop_event is set.

        Checks stop_event at the top of every iteration so it always exits
        at a clean batch boundary — never mid-batch.

        Args:
            batch_size: Max jobs per batch iteration.
            stop_event: When set, drain exits at the next batch boundary.

        Returns:
            Total number of jobs processed across all batches.
        """
        total = 0
        while not stop_event.is_set():
            processed = await self._run_batch(batch_size)
            if processed == 0:
                break
            total += processed
        return total

    async def _run_batch(self, batch_size: int) -> int:
        """Fetch up to *batch_size* PENDING rows and process them concurrently.

        Returns:
            Number of rows that were dispatched (may be 0 if queue is empty).
        """
        async with self._session_factory() as session:
            queue_repo = self._queue_repo_factory(session)
            rows = await queue_repo.list_pending(batch_size)

        if not rows:
            return 0

        run_id = uuid.uuid4()
        sem = asyncio.Semaphore(self._settings.max_concurrent_requests)
        await asyncio.gather(
            *(self._process(row.id, row.url, run_id, sem) for row in rows),
            return_exceptions=True,
        )
        return len(rows)

    async def run(self, *, limit: int | None = None) -> uuid.UUID:
        """Drain PENDING rows and dispatch them concurrently.

        Generates one run_id for the batch. All Provenance rows written in
        this call share that run_id. Concurrency is capped at
        settings.max_concurrent_requests via an asyncio.Semaphore.

        Args:
            limit: Maximum number of PENDING rows to process in this batch.
                   Defaults to max_concurrent_requests when not specified.

        Returns:
            The UUID assigned to this batch (shared across all Provenance rows).
        """
        run_id = uuid.uuid4()
        effective_limit = (
            limit if limit is not None else self._settings.max_concurrent_requests
        )

        async with self._session_factory() as session:
            queue_repo = self._queue_repo_factory(session)
            rows = await queue_repo.list_pending(effective_limit)

        sem = asyncio.Semaphore(self._settings.max_concurrent_requests)
        await asyncio.gather(
            *(self._process(row.id, row.url, run_id, sem) for row in rows),
            return_exceptions=True,
        )
        return run_id

    async def _process(
        self,
        row_id: int,
        url: str,
        run_id: uuid.UUID,
        sem: asyncio.Semaphore,
    ) -> None:
        """Process a single queue row inside its own session/transaction.

        Lifecycle:
          1. Acquire semaphore slot
          2. Open a new session (own transaction)
          3. Reload the row and mark IN_PROGRESS → commit
          4. Scrape via scraper.fetch_and_parse(url)
          5. Read scraper.last_html → compute SHA256
          6. Write Provenance(SUCCESS) + mark DONE → commit
          On exception:
          7. Rollback; open a new session for the failure record
          8. Write mark_failed (ceiling logic owned by repo) → commit
        """
        async with sem:
            async with self._session_factory() as session:
                queue_repo = self._queue_repo_factory(session)
                prov_repo = self._provenance_repo_factory(session)

                row = await queue_repo.get(row_id)
                if row is None:
                    logger.warning("Row %s vanished before processing", row_id)
                    return

                await queue_repo.mark_in_progress(row)
                await session.commit()

                try:
                    scraper = self._scraper_factory(url)
                    await scraper.fetch_and_parse(url)
                    raw_html: str = scraper.last_html
                    content_hash = hashlib.sha256(
                        raw_html.encode("utf-8")
                    ).hexdigest()

                    prov = self._provenance_factory(
                        url, "SUCCESS", content_hash, run_id
                    )
                    await prov_repo.create(prov)
                    await queue_repo.mark_done(row)
                    await session.commit()

                    logger.info(
                        "Job completed",
                        extra={"url": url, "run_id": str(run_id)},
                    )

                except (ScraperError, RepositoryError) as exc:
                    logger.warning(
                        "Job failed",
                        extra={"url": url, "error": str(exc)},
                    )
                    await session.rollback()

                    try:
                        async with self._session_factory() as fail_session:
                            fail_queue_repo = self._queue_repo_factory(fail_session)
                            fail_row = await fail_queue_repo.get(row_id)
                            if fail_row is None:
                                return
                            new_status = await fail_queue_repo.mark_failed(
                                fail_row, str(exc), self._settings.max_queue_retries
                            )
                            await fail_session.commit()
                    except Exception as mark_err:
                        logger.error(
                            "Failed to mark job %s as failed: %s",
                            row_id, mark_err, exc_info=False,
                        )
                        return

                    logger.info(
                        "Job marked failed",
                        extra={
                            "url": url,
                            "new_status": str(new_status),
                            "run_id": str(run_id),
                        },
                    )
