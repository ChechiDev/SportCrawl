"""Composition root for the work server.

Builds the shared engine/session factory, wires ScrapeQueueWorkAdapter,
creates an aiohttp AppRunner + TCPSite, and launches JobLoop as an
asyncio.create_task in the SAME event loop.

Shutdown sequence (REQ-9.7, 30s budget):
  1. SIGTERM/SIGINT → stop_event.set()
  2. site.stop() + runner.cleanup()     — stop accepting HTTP requests
  3. await jobloop_task (timeout=30s)   — drain in-flight batch
  4. engine.dispose()                   — close DB connection pool

This module MUST NOT import from infrastructure.jobs or
infrastructure.persistence beyond what is required for the composition root
(import-linter: work_server ⟂ jobs, work_server ⟂ persistence enforced in
the independence contract in pyproject.toml).

NOTE: The independence contract is declared as an independence contract on
the four infrastructure sub-packages. The composition root necessarily imports
from sibling packages to wire them together — this is expected and correct.
The contract prevents the *server.py* handler layer from importing jobs/persistence
directly; the runtime.py composition root is the wiring boundary.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from collections.abc import Callable
from typing import Any, cast

from aiohttp import web
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config.settings import Settings
from infrastructure.jobs.job_loop import JobLoop
from infrastructure.persistence.adapters.work_queue import ScrapeQueueWorkAdapter
from infrastructure.work_server.server import create_app

logger = logging.getLogger(__name__)

_SHUTDOWN_TIMEOUT = 30.0  # seconds — REQ-9.7


# ---------------------------------------------------------------------------
# JobLoop background coroutine
# ---------------------------------------------------------------------------


async def _jobloop_forever(job_loop: JobLoop, poll_interval: float) -> None:
    """Run JobLoop.run() in a tight poll loop until cancelled.

    Sleeps poll_interval seconds between batches.  CancelledError propagates
    normally so the task can be awaited and cancelled during shutdown.
    """
    while True:
        try:
            await job_loop.run()
        except Exception:
            logger.exception("JobLoop.run() raised an unexpected error; continuing")
        await asyncio.sleep(poll_interval)


# ---------------------------------------------------------------------------
# Scraper factory
# ---------------------------------------------------------------------------


def make_scraper_factory(
    browser_engine: Any,
    scraping: Any,
    session_factory: async_sessionmaker[AsyncSession],
) -> Callable[[str], Any]:
    """Return a URL-routing factory that maps URLs to concrete BaseScraper instances.

    Args:
        browser_engine: Shared PydollEngine instance (injected by the composition root).
        scraping:        ScrapingSettings instance.
        session_factory: Async session factory for scrapers that need DB persistence.

    Returns:
        A callable ``factory(url: str) -> BaseScraper`` that raises ScraperError
        when no scraper is registered for the given URL.
    """
    from core.exceptions.scraper import ScraperError
    from infrastructure.scraping.countries import CountryScraper

    def _factory(url: str) -> Any:
        if "fbref.com/en/countries" in url:
            return CountryScraper(browser_engine, scraping, session_factory)
        raise ScraperError(f"No scraper registered for URL: {url}")

    return _factory


# ---------------------------------------------------------------------------
# Composition root
# ---------------------------------------------------------------------------


async def serve(settings: Settings) -> None:
    """Build and run the work server with a shared event loop.

    Args:
        settings: A Settings (or compatible mock) instance providing:
            settings.db               — DatabaseSettings for engine creation
            settings.scraping.work_server_token — bearer auth token
            settings.scraping.work_server_host  — bind address
            settings.scraping.work_server_port  — TCP port
            settings.scraping.poll_interval     — JobLoop poll cadence (seconds)
    """
    from sqlalchemy.engine.url import URL

    db = settings.db
    scraping = settings.scraping

    # --- Build engine + session factory ---
    dsn = URL.create(
        drivername="postgresql+asyncpg",
        username=db.user,
        password=db.password.get_secret_value(),
        host=db.host,
        port=db.port,
        database=db.name,
    )
    connect_args: dict[str, object] = {}
    if getattr(db, "ssl_mode", None) == "require":
        connect_args["ssl"] = True
    elif getattr(db, "ssl_mode", None) == "disable":
        connect_args["ssl"] = False

    engine = create_async_engine(
        dsn,
        pool_size=getattr(db, "pool_size", 5),
        max_overflow=getattr(db, "max_overflow", 10),
        pool_timeout=float(getattr(db, "pool_timeout", 30)),
        pool_recycle=getattr(db, "pool_recycle", 1800),
        pool_pre_ping=True,
        connect_args=connect_args,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)

    # --- Build WorkQueuePort adapter ---
    adapter = ScrapeQueueWorkAdapter(factory)

    # --- Build aiohttp application ---
    token: str = scraping.work_server_token.get_secret_value()
    app = create_app(adapter, token)

    # --- Build JobLoop (dependency injection — no direct model imports) ---
    from infrastructure.browser.pydoll_engine import PydollEngine
    from infrastructure.persistence.models.provenance import Provenance
    from infrastructure.persistence.repositories.provenance import ProvenanceRepository
    from infrastructure.persistence.repositories.scrape_queue import (
        ScrapeQueueRepository,
    )
    from infrastructure.persistence.session import get_session

    browser_engine = PydollEngine()
    scraper_factory = make_scraper_factory(browser_engine, scraping, factory)

    job_loop = JobLoop(
        session_factory=lambda: get_session(factory),
        scraper_factory=scraper_factory,
        queue_repo_factory=lambda session: ScrapeQueueRepository(  # type: ignore
            cast(AsyncSession, session)
        ),
        provenance_repo_factory=lambda session: ProvenanceRepository(
            cast(AsyncSession, session)
        ),
        provenance_factory=lambda url, outcome, content_hash, run_id: Provenance(
            url=url, outcome=outcome, content_hash=content_hash, run_id=run_id
        ),
        settings=scraping,
    )

    # --- Start AppRunner + TCPSite ---
    runner = web.AppRunner(app)
    await runner.setup()

    host: str = getattr(scraping, "work_server_host", "127.0.0.1")
    port: int = getattr(scraping, "work_server_port", 9731)
    site = web.TCPSite(runner, host, port)
    await site.start()

    logger.info("Work server listening on %s:%s", host, port)

    # --- Launch JobLoop background task ---
    poll_interval: float = getattr(scraping, "poll_interval", 5.0)
    jobloop_task = asyncio.create_task(
        _jobloop_forever(job_loop, poll_interval),
        name="jobloop",
    )

    # --- Install signal handlers ---
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _request_shutdown(sig_num: int) -> None:
        logger.info("Received signal %s — initiating shutdown", sig_num)
        stop_event.set()

    loop.add_signal_handler(signal.SIGTERM, _request_shutdown, signal.SIGTERM)
    loop.add_signal_handler(signal.SIGINT, _request_shutdown, signal.SIGINT)

    # --- Wait for shutdown signal ---
    await stop_event.wait()

    logger.info("Shutdown initiated — stopping HTTP site")

    # --- Shutdown sequence (REQ-9.7) ---
    # 1. Stop HTTP ingress
    await site.stop()
    await runner.cleanup()

    # 2. Drain in-flight JobLoop batch (30s timeout)
    jobloop_task.cancel()
    try:
        await asyncio.wait_for(jobloop_task, timeout=_SHUTDOWN_TIMEOUT)
    except (TimeoutError, asyncio.CancelledError):
        pass

    # 3. Close browser engine
    try:
        await browser_engine.close()
    except Exception:
        logger.debug("browser_engine.close() raised during shutdown; ignoring")

    # 4. Close DB connection pool
    await engine.dispose()

    logger.info("Shutdown complete")


if __name__ == "__main__":
    import sys

    _settings = Settings()  # type: ignore[call-arg]  # pydantic-settings reads from env
    logging.basicConfig(
        level=getattr(logging, _settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )
    asyncio.run(serve(_settings))
