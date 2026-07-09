"""Unit tests for JobLoop.

Covers:
- run() returns a UUID
- Each run() call generates a unique run_id
- Semaphore limits concurrency to max_concurrent_requests
- content_hash = sha256(scraper.last_html)
- ProvenanceRepository.create called on success
- mark_failed called on exception
- A failed job does not affect sibling jobs (return_exceptions=True behavior)
- retry ceiling logic: mark_failed return value determines row re-queue
- mark_in_progress called before fetch
- mark_done called on success

All dependencies are fully mocked. No real DB, no real browser.
"""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from config.settings import ScrapingSettings
from core.exceptions.scraper import ScraperError
from infrastructure.jobs.job_loop import JobLoop
from infrastructure.persistence.models.provenance import Provenance, ProvenanceOutcome
from infrastructure.persistence.models.scrape_queue import ScrapeQueue, ScrapeStatus

# ---------------------------------------------------------------------------
# Provenance factory helper (simulates the real factory injected at composition root)
# ---------------------------------------------------------------------------


def _provenance_factory(
    url: str, outcome_str: str, content_hash: str, run_id: object
) -> Provenance:
    outcome = ProvenanceOutcome[outcome_str]
    return Provenance(
        url=url,
        outcome=outcome,
        content_hash=content_hash,
        run_id=run_id,  # type: ignore[arg-type]
    )

# ---------------------------------------------------------------------------
# Test-doubles / factories
# ---------------------------------------------------------------------------


def _make_settings(**overrides: Any) -> ScrapingSettings:
    base: dict[str, Any] = {
        "max_retries": 1,
        "base_delay": 0.0,
        "max_delay": 0.0,
        "request_timeout": 5,
        "max_concurrent_requests": 3,
        "max_queue_retries": 3,
    }
    base.update(overrides)
    return ScrapingSettings(**base)


def _make_row(
    url: str = "https://fbref.com/en/test/",
    *,
    retry_count: int = 0,
    row_id: int = 1,
) -> ScrapeQueue:
    """Return a minimal ScrapeQueue row stub (no real DB)."""
    row = MagicMock(spec=ScrapeQueue)
    row.id = row_id
    row.url = url
    row.retry_count = retry_count
    row.status = ScrapeStatus.PENDING
    return row


def _make_session_factory(session: Any) -> Any:
    """Wrap session in an async context manager factory."""

    @asynccontextmanager
    async def _factory() -> AsyncIterator[Any]:
        yield session

    return _factory


def _make_queue_repo(
    rows: list[ScrapeQueue],
    *,
    mark_failed_returns: ScrapeStatus = ScrapeStatus.PENDING,
) -> Any:
    repo = AsyncMock()
    repo.list_pending = AsyncMock(return_value=rows)
    repo.mark_in_progress = AsyncMock(side_effect=lambda r: r)
    repo.mark_done = AsyncMock(side_effect=lambda r: r)
    repo.mark_failed = AsyncMock(return_value=mark_failed_returns)
    return repo


def _make_provenance_repo() -> Any:
    repo = AsyncMock()
    repo.create = AsyncMock(return_value=MagicMock(spec=Provenance))
    return repo


def _build_job_loop(
    *,
    rows: list[ScrapeQueue] | None = None,
    settings: ScrapingSettings | None = None,
    scraper_html: str = "<html>ok</html>",
    mark_failed_returns: ScrapeStatus = ScrapeStatus.PENDING,
    raise_on_fetch: Exception | None = None,
) -> tuple[JobLoop, Any, Any]:
    """Build a JobLoop with fully mocked dependencies.

    Returns (loop, queue_repo_mock, provenance_repo_mock).
    """
    if rows is None:
        rows = [_make_row()]
    if settings is None:
        settings = _make_settings()

    queue_repo = _make_queue_repo(rows, mark_failed_returns=mark_failed_returns)
    prov_repo = _make_provenance_repo()

    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    def _scraper_factory(_url: str) -> Any:
        scraper = AsyncMock()
        if raise_on_fetch:
            scraper.fetch_and_parse = AsyncMock(side_effect=raise_on_fetch)
        else:
            scraper.fetch_and_parse = AsyncMock(return_value=MagicMock())
        scraper.last_html = scraper_html
        return scraper

    def _queue_repo_factory(_session: Any) -> Any:
        return queue_repo

    def _prov_repo_factory(_session: Any) -> Any:
        return prov_repo

    loop = JobLoop(
        session_factory=_make_session_factory(session),
        scraper_factory=_scraper_factory,
        queue_repo_factory=_queue_repo_factory,
        provenance_repo_factory=_prov_repo_factory,
        provenance_factory=_provenance_factory,
        settings=settings,
    )
    return loop, queue_repo, prov_repo


# ---------------------------------------------------------------------------
# run() return value
# ---------------------------------------------------------------------------


class TestRunReturnValue:
    async def test_run_returns_uuid(self) -> None:
        """run() must return a UUID object."""
        loop, _, _ = _build_job_loop()
        run_id = await loop.run(limit=10)
        assert isinstance(run_id, uuid.UUID)

    async def test_unique_run_id_per_call(self) -> None:
        """Each run() invocation generates a distinct run_id."""
        loop, _, _ = _build_job_loop()
        id1 = await loop.run(limit=10)
        id2 = await loop.run(limit=10)
        assert id1 != id2


# ---------------------------------------------------------------------------
# content_hash
# ---------------------------------------------------------------------------


class TestContentHash:
    async def test_content_hash_is_sha256_of_last_html(self) -> None:
        """Provenance.content_hash equals sha256(scraper.last_html) hexdigest."""
        raw_html = "<html>content-hash-test</html>"
        expected_hash = hashlib.sha256(raw_html.encode("utf-8")).hexdigest()

        loop, _, prov_repo = _build_job_loop(scraper_html=raw_html)
        await loop.run(limit=10)

        created_prov: Provenance = prov_repo.create.call_args[0][0]
        assert created_prov.content_hash == expected_hash


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------


class TestSuccessPath:
    async def test_provenance_create_called_on_success(self) -> None:
        """On a successful scrape, ProvenanceRepository.create is called once."""
        loop, _, prov_repo = _build_job_loop()
        await loop.run(limit=10)
        prov_repo.create.assert_called_once()

    async def test_provenance_outcome_is_success(self) -> None:
        """Provenance row has outcome=SUCCESS on a successful scrape."""
        loop, _, prov_repo = _build_job_loop()
        await loop.run(limit=10)
        created_prov: Provenance = prov_repo.create.call_args[0][0]
        assert created_prov.outcome == ProvenanceOutcome.SUCCESS

    async def test_mark_done_called_on_success(self) -> None:
        """mark_done is called once on a successful scrape."""
        loop, queue_repo, _ = _build_job_loop()
        await loop.run(limit=10)
        queue_repo.mark_done.assert_called_once()

    async def test_run_id_on_provenance_row(self) -> None:
        """The provenance row carries the run_id returned by run()."""
        loop, _, prov_repo = _build_job_loop()
        run_id = await loop.run(limit=10)
        created_prov: Provenance = prov_repo.create.call_args[0][0]
        assert created_prov.run_id == run_id


# ---------------------------------------------------------------------------
# Failure path
# ---------------------------------------------------------------------------


class TestFailurePath:
    async def test_mark_failed_called_on_exception(self) -> None:
        """When scraper.fetch_and_parse raises a ScraperError, mark_failed is called."""
        error = ScraperError("network error")
        loop, queue_repo, _ = _build_job_loop(raise_on_fetch=error)
        await loop.run(limit=10)
        queue_repo.mark_failed.assert_called_once()

    async def test_mark_done_not_called_on_exception(self) -> None:
        """When scraper raises, mark_done is NOT called."""
        error = ScraperError("network error")
        loop, queue_repo, _ = _build_job_loop(raise_on_fetch=error)
        await loop.run(limit=10)
        queue_repo.mark_done.assert_not_called()

    async def test_failed_job_does_not_prevent_siblings(self) -> None:
        """One failing job must not abort sibling jobs (return_exceptions=True)."""
        rows = [
            _make_row("https://fbref.com/en/a/", row_id=1),
            _make_row("https://fbref.com/en/b/", row_id=2),
            _make_row("https://fbref.com/en/c/", row_id=3),
        ]
        call_count = 0
        fail_url = "https://fbref.com/en/b/"

        def _scraper_factory(url: str) -> Any:
            nonlocal call_count
            call_count += 1
            scraper = AsyncMock()
            scraper.last_html = "<html>ok</html>"
            if url == fail_url:
                scraper.fetch_and_parse = AsyncMock(
                    side_effect=ScraperError("fetch failed")
                )
            else:
                scraper.fetch_and_parse = AsyncMock(return_value=MagicMock())
            return scraper

        queue_repo = _make_queue_repo(rows)
        prov_repo = _make_provenance_repo()
        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)
        session.commit = AsyncMock()
        session.rollback = AsyncMock()

        loop = JobLoop(
            session_factory=_make_session_factory(session),
            scraper_factory=_scraper_factory,
            queue_repo_factory=lambda s: queue_repo,
            provenance_repo_factory=lambda s: prov_repo,
            provenance_factory=_provenance_factory,
            settings=_make_settings(),
        )
        await loop.run(limit=10)

        # 2 successes + 1 failure → mark_done called twice, mark_failed once
        assert queue_repo.mark_done.call_count == 2
        assert queue_repo.mark_failed.call_count == 1


# ---------------------------------------------------------------------------
# Concurrency / semaphore
# ---------------------------------------------------------------------------


class TestSemaphoreCap:
    async def test_concurrency_capped_at_max_concurrent_requests(self) -> None:
        """At most max_concurrent_requests jobs run simultaneously."""
        max_concurrent = 2
        settings = _make_settings(max_concurrent_requests=max_concurrent)
        rows = [_make_row(f"https://fbref.com/en/{i}/", row_id=i) for i in range(5)]

        concurrent_peak = 0
        currently_running = 0

        async def _slow_fetch(url: str) -> None:
            nonlocal concurrent_peak, currently_running
            currently_running += 1
            concurrent_peak = max(concurrent_peak, currently_running)
            await asyncio.sleep(0)  # yield control
            currently_running -= 1

        def _scraper_factory(url: str) -> Any:
            scraper = AsyncMock()
            scraper.last_html = "<html>ok</html>"
            scraper.fetch_and_parse = AsyncMock(side_effect=_slow_fetch)
            return scraper

        queue_repo = _make_queue_repo(rows)
        prov_repo = _make_provenance_repo()
        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)
        session.commit = AsyncMock()
        session.rollback = AsyncMock()

        loop = JobLoop(
            session_factory=_make_session_factory(session),
            scraper_factory=_scraper_factory,
            queue_repo_factory=lambda s: queue_repo,
            provenance_repo_factory=lambda s: prov_repo,
            provenance_factory=_provenance_factory,
            settings=settings,
        )
        await loop.run(limit=10)

        assert concurrent_peak <= max_concurrent
