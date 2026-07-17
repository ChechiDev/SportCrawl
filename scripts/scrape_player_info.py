"""Player info scraper — fetches biographical data from FBRef player profile pages.

Usage:
    uv run python scripts/scrape_player_info.py --workers 2
    uv run python scripts/scrape_player_info.py --workers 3 --seed
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import random
import time

import sqlalchemy as sa
from pydoll.exceptions import BrowserException
from rich.console import Console, Group
from rich.live import Live
from rich.logging import RichHandler
from rich.markup import escape
from rich.rule import Rule
from rich.table import Table
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config.settings import Settings
from core.application.scrape_job_processor import ScrapeJobProcessor
from core.exceptions.scraper import PageLoadError, RateLimitError
from infrastructure.browser.pydoll_engine import PydollEngine
from infrastructure.persistence.models.scrape_queue import ScrapeQueue, ScrapeStatus
from infrastructure.persistence.models.shared.player import Player
from infrastructure.persistence.repositories.player_info import PlayerInfoRepository
from infrastructure.persistence.repositories.player_info_queue import (
    PlayerInfoQueueRepository,
)
from infrastructure.persistence.session import create_session_factory, get_session
from infrastructure.scraping.player_info import PlayerInfoScraper

_console = Console(stderr=True)
logging.basicConfig(
    level=logging.WARNING,
    format="%(message)s",
    handlers=[RichHandler(console=_console, show_time=False, show_path=False)],
)
logger = logging.getLogger(__name__)

# Silence noisy third-party loggers
for _noisy in ("pydoll", "websockets", "asyncio"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# Position resolver
# ---------------------------------------------------------------------------


async def _load_country_ids(
    session_factory: async_sessionmaker[AsyncSession],
) -> frozenset[str]:
    """Load all valid country_id values from tbl_countries into a frozenset."""
    async with get_session(session_factory) as session:
        result = await session.execute(
            sa.text("SELECT country_id FROM sch_shared.tbl_countries")
        )
        return frozenset(row[0] for row in result.fetchall())


async def _load_country_name_cache(
    session_factory: async_sessionmaker[AsyncSession],
) -> dict[str, str]:
    """Load a country_name → country_id mapping from tbl_countries.

    Used to resolve scraped country name strings to FK values.
    """
    async with get_session(session_factory) as session:
        result = await session.execute(
            sa.text(
                "SELECT country_name, country_id FROM sch_shared.tbl_countries"
            )
        )
        return {row[0]: row[1] for row in result.fetchall()}


# ---------------------------------------------------------------------------
# Worker coroutine
# ---------------------------------------------------------------------------


def _build_table(worker_status: dict[int, str], num_workers: int) -> Group:
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold green")
    table.add_column()
    for i in range(1, num_workers + 1):
        table.add_row(
            "RUN", escape(worker_status.get(i, f"[Crawl-{i}] starting crawl..."))
        )
    return Group(Rule(), table)


async def _display_loop(
    num_workers: int,
    worker_status: dict[int, str],
    stop_event: asyncio.Event,
    live: Live,
) -> None:
    while not stop_event.is_set():
        live.update(_build_table(worker_status, num_workers))
        await asyncio.sleep(0.5)
    live.update(_build_table(worker_status, num_workers))


async def _worker(
    worker_id: int,
    session_factory: async_sessionmaker[AsyncSession],
    fetch_gate: asyncio.Semaphore,
    chrome_profile_base: str,
    position_cache: dict[str, int],
    valid_countries: frozenset[str],
    country_name_cache: dict[str, str],
    worker_status: dict[int, str],
    total_jobs: int = 0,
    already_done: int = 0,
) -> int:
    """Process player_info jobs from scrape_queue until the queue is empty.

    Owns: browser engine lifetime, job claiming loop, HTML fetch, progress display.
    Delegates: parse → FK resolution → persist → mark done/failed to ScrapeJobProcessor.

    Args:
        worker_id: Integer identifier for this worker (1-based). Used to
            isolate Chrome profile directories so multiple workers can
            run concurrently without SingletonLock conflicts.
        session_factory: Async SQLAlchemy session factory.

    Returns:
        Number of jobs successfully processed.
    """
    processed = 0

    try:
        profile_dir = f"{chrome_profile_base}-{worker_id}"
        engine_ctx = PydollEngine(profile_dir=profile_dir, name=f"Crawl-{worker_id}")
    except Exception as exc:
        logger.error("[worker-%d] engine init failed: %s", worker_id, exc)
        return 0

    async with engine_ctx as engine:
        while True:
            async with get_session(session_factory) as session:
                queue_repo = PlayerInfoQueueRepository(session)
                job = await queue_repo.claim_next()
                await session.commit()

            if job is None:
                break

            attempt = 0
            success = False

            while attempt < 3 and not success:
                try:
                    async with fetch_gate:
                        html = await engine.fetch(job.url)
                    # cooldown outside gate so other workers don't block waiting
                    await asyncio.sleep(random.uniform(5, 15))
                    if not html:
                        raise RuntimeError("empty HTML response")

                    scraper = PlayerInfoScraper(
                        player_id=_player_id_from_url(job.url),
                        player_info_url=job.url,
                    )

                    async with get_session(session_factory) as session:
                        info_repo = PlayerInfoRepository(session)
                        q_repo = PlayerInfoQueueRepository(session)
                        processor = ScrapeJobProcessor(
                            scraper=scraper,
                            queue_repo=q_repo,
                            player_info_repo=info_repo,
                            country_name_cache=country_name_cache,
                            position_cache=position_cache,
                            valid_countries=valid_countries,
                        )
                        await processor.process(job, html)
                        await session.commit()

                    success = True
                    processed += 1
                    global_done = already_done + processed
                    progress = (
                        f"[{global_done}/{total_jobs}]"
                        if total_jobs
                        else f"[{global_done}]"
                    )
                    worker_status[worker_id] = (
                        f"[Crawl-{worker_id}] {progress} scraped: {processed}"
                    )

                except (
                    PageLoadError, RateLimitError, BrowserException, RuntimeError
                ) as exc:
                    attempt += 1
                    logger.warning(
                        "[worker-%d] job %d attempt %d failed: %s",
                        worker_id, job.id, attempt, exc,
                        exc_info=True,
                    )
                    is_terminal = isinstance(exc, BrowserException) or attempt >= 3
                    if is_terminal:
                        async with get_session(session_factory) as session:
                            q_repo = PlayerInfoQueueRepository(session)
                            await q_repo.mark_failed(job.id, str(exc))
                            await session.commit()
                    else:
                        await asyncio.sleep(2)
                    # Browser is unrecoverable — exit worker so the job can be
                    # retried by recover_stale() on the next run
                    if isinstance(exc, BrowserException):
                        logger.error(
                            "[worker-%d] browser failure — shutting down worker",
                            worker_id,
                        )
                        return processed

            if not success:
                logger.error(
                    "[worker-%d] job %d exhausted retries, giving up",
                    worker_id,
                    job.id,
                )

    logger.debug("[worker-%d] done — processed %d jobs", worker_id, processed)
    return processed


def _player_id_from_url(url: str) -> str:
    """Extract FBRef player slug from profile URL.

    Example:
        https://fbref.com/en/players/abc12345/Test-Player → 'abc12345'

    Falls back to the raw URL when the expected path structure is absent.
    """
    parts = url.rstrip("/").split("/")
    try:
        idx = parts.index("players")
        return parts[idx + 1]
    except (ValueError, IndexError):
        return url


# ---------------------------------------------------------------------------
# Queue seeder (--seed flag)
# ---------------------------------------------------------------------------


async def _seed_queue(
    session_factory: async_sessionmaker[AsyncSession],
) -> int:
    """Seed scrape_queue with one player_info row per player in tbl_players.

    Uses ON CONFLICT(url) DO NOTHING so repeated --seed calls are idempotent.

    Args:
        session_factory: Async SQLAlchemy session factory.

    Returns:
        Number of newly inserted rows (0 when all players already queued).
    """
    async with get_session(session_factory) as session:
        result = await session.execute(
            sa.select(Player.player_id, Player.player_url)
        )
        players = result.fetchall()

    if not players:
        logger.info("seed: tbl_players is empty — nothing to seed")
        return 0

    rows = [
        {
            "url": row.player_url,
            "domain": "fbref.com",
            "status": ScrapeStatus.PENDING,
            "job_type": "player_info",
        }
        for row in players
    ]

    # asyncpg limit: 32767 params per query; 4 columns per row → max 8191 rows/chunk
    chunk_size = 8191
    inserted = 0
    for i in range(0, len(rows), chunk_size):
        chunk = rows[i : i + chunk_size]
        stmt = pg_insert(ScrapeQueue).values(chunk)
        stmt = stmt.on_conflict_do_nothing(index_elements=["url", "job_type"])
        async with get_session(session_factory) as session:
            result = await session.execute(stmt)
            inserted += getattr(result, "rowcount", None) or 0
            await session.commit()

    logger.info("seed: inserted %d new player_info jobs into scrape_queue", inserted)
    return inserted


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


async def main(workers: int | None = None, seed: bool | None = None) -> None:
    if workers is None or seed is None:
        parser = argparse.ArgumentParser(
            description="Scrape FBRef player info pages."
        )
        parser.add_argument(
            "--workers",
            metavar="N",
            type=int,
            default=1,
            choices=range(1, 26),
            help="Number of parallel worker coroutines (1–25, default: 1).",
        )
        parser.add_argument(
            "--seed",
            action="store_true",
            help=(
                "Seed scrape_queue with player_info rows from tbl_players "
                "before launching workers."
            ),
        )
        parser.parse_args()
        if workers is None:
            workers = workers
        if seed is None:
            seed = seed

    settings = Settings()  # type: ignore[call-arg]

    # Ensure pool can serve all workers without starvation
    settings.db.pool_size = max(workers * 2, settings.db.pool_size)

    session_factory = create_session_factory(settings.db)

    # Recover any stale IN_PROGRESS rows from a previous interrupted run
    async with get_session(session_factory) as session:
        queue_repo = PlayerInfoQueueRepository(session)
        stale = await queue_repo.recover_stale()
        await session.commit()
    if stale:
        logger.info("Recovered %d stale jobs back to PENDING", stale)

    if seed:
        seeded = await _seed_queue(session_factory)
        logger.info("Seeded %d player_info jobs", seeded)

    async with get_session(session_factory) as session:
        result = await session.execute(
            sa.text(
                "SELECT count(*) FROM sch_infra.scrape_queue"
                " WHERE job_type='player_info' AND status='PENDING'"
            )
        )
        pending_total = result.scalar() or 0
        result = await session.execute(
            sa.text("SELECT count(*) FROM sch_shared.tbl_player_info")
        )
        already_done = int(result.scalar() or 0)

    # One request at a time globally — workers parse/write DB in parallel
    fetch_gate = asyncio.Semaphore(1)

    valid_countries = await _load_country_ids(session_factory)
    country_name_cache = await _load_country_name_cache(session_factory)
    position_cache: dict[str, int] = {}

    logger.info(
        "Launching %d worker(s)… (%d done, %d pending, %d total)",
        workers, already_done, pending_total, already_done + pending_total,
    )

    worker_status: dict[int, str] = {}
    stop_event = asyncio.Event()

    t0 = time.monotonic()
    with Live(
        _build_table(worker_status, workers),
        console=_console,
        refresh_per_second=2,
    ) as live:
        display_task = asyncio.create_task(
            _display_loop(workers, worker_status, stop_event, live)
        )
        results = await asyncio.gather(
            *[
                _worker(
                    worker_id=i + 1,
                    session_factory=session_factory,
                    fetch_gate=fetch_gate,
                    chrome_profile_base=settings.scraping.chrome_profile_dir,
                    position_cache=position_cache,
                    valid_countries=valid_countries,
                    country_name_cache=country_name_cache,
                    worker_status=worker_status,
                    total_jobs=already_done + pending_total,
                    already_done=already_done,
                )
                for i in range(workers)
            ]
        )
        stop_event.set()
        await display_task
    elapsed = time.monotonic() - t0
    total = sum(results)
    rate = total / elapsed if elapsed > 0 else 0
    eta_hours = (pending_total - total) / (rate * 3600) if rate > 0 else float("inf")
    logger.info(
        "Done. workers=%d | scraped=%d | elapsed=%.1fs"
        " | rate=%.2f/s | ETA full run=%.1fh",
        workers, total, elapsed, rate, eta_hours,
    )


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
