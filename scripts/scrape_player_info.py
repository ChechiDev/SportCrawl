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
    handlers=[
        RichHandler(
            console=_console,
            show_time=False,
            show_path=False,
            rich_tracebacks=False,
        ),
    ],
)
for _noisy in ("pydoll", "websockets", "asyncio"):
    logging.getLogger(_noisy).setLevel(logging.CRITICAL)
logger = logging.getLogger(__name__)


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


def _build_table(
    worker_labels: dict[int, str],
    worker_counts: dict[int, int],
    num_workers: int,
    already_done: int,
    total_jobs: int,
) -> Group:
    global_done = already_done + sum(worker_counts.values())
    total_str = f"{global_done}/{total_jobs}" if total_jobs else str(global_done)
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold green")
    table.add_column()
    for i in range(1, num_workers + 1):
        own = worker_counts.get(i, 0)
        label = worker_labels.get(i, "starting crawl...")
        base = escape(f"[Crawl-{i}] [{own} | {total_str}] ")
        table.add_row("RUN", base + label)
    return Group(table)


async def _display_loop(
    num_workers: int,
    worker_labels: dict[int, str],
    worker_counts: dict[int, int],
    already_done: int,
    total_jobs: int,
    stop_event: asyncio.Event,
    live: Live,
) -> None:
    while not stop_event.is_set():
        table = _build_table(
            worker_labels, worker_counts, num_workers, already_done, total_jobs
        )
        live.update(table)
        await asyncio.sleep(0.5)
    table = _build_table(
        worker_labels, worker_counts, num_workers, already_done, total_jobs
    )
    live.update(table)


async def _worker(
    worker_id: int,
    session_factory: async_sessionmaker[AsyncSession],
    fetch_gate: asyncio.Semaphore,
    chrome_profile_base: str,
    position_cache: dict[str, int],
    valid_countries: frozenset[str],
    country_name_cache: dict[str, str],
    worker_labels: dict[int, str],
    worker_counts: dict[int, int],
    fbref_base_url: str = "https://fbref.com",
    step2_done: asyncio.Event | None = None,
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

    startup_delay = random.uniform(3.0, 15.0)
    worker_labels[worker_id] = f"waiting {startup_delay:.1f}s before start..."
    await asyncio.sleep(startup_delay)

    profile_dir = f"{chrome_profile_base}-{worker_id}"

    max_restarts = 5
    restart_count = 0
    while True:
        browser_started = False
        try:
            async with PydollEngine(
                profile_dir=profile_dir, name=f"Crawl-{worker_id}"
            ) as engine:
                browser_started = True
                restart_count = 0  # reset on successful start
                worker_labels[worker_id] = "starting crawl..."

                while True:
                    async with get_session(session_factory) as session:
                        queue_repo = PlayerInfoQueueRepository(session)
                        job = await queue_repo.claim_next()
                        await session.commit()

                    if job is None:
                        if step2_done is None or step2_done.is_set():
                            return processed
                        worker_labels[worker_id] = "waiting for step 2..."
                        await asyncio.sleep(10)
                        continue

                    attempt = 0
                    success = False
                    browser_restart = False

                    while attempt < 3 and not success:
                        try:
                            async with fetch_gate:
                                await engine.navigate(fbref_base_url + job.url)
                            # Challenge polling and cooldown run outside gate so other
                            # workers are not blocked during Cloudflare resolution.
                            html = await engine.wait_for_challenge(
                                fbref_base_url + job.url
                            )
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
                                result = await processor.process(job, html)
                                await session.commit()

                            success = True
                            processed += 1
                            worker_counts[worker_id] = processed
                            full_name = result[0] if result else "unknown"
                            worker_labels[worker_id] = escape(full_name or "unknown")

                        except (
                            PageLoadError, RateLimitError, BrowserException, RuntimeError  # noqa: E501
                        ) as exc:
                            attempt += 1
                            if isinstance(exc, BrowserException):
                                worker_labels[worker_id] = (
                                    "[bold red]browser error — restarting[/bold red]"
                                )
                                try:
                                    async with get_session(session_factory) as session:
                                        q_repo = PlayerInfoQueueRepository(session)
                                        await q_repo.mark_failed(job.id, str(exc))
                                        await session.commit()
                                except Exception as mark_err:
                                    worker_labels[worker_id] = (
                                        "[bold red]mark_failed error: "
                                        f"{escape(str(mark_err))}[/bold red]"
                                    )
                                browser_restart = True
                                break
                            is_terminal = attempt >= 3
                            if is_terminal:
                                worker_labels[worker_id] = (
                                    f"[bold red]FAILED job {job.id}"
                                    f" — {escape(str(exc))}[/bold red]"
                                )
                                try:
                                    async with get_session(session_factory) as session:
                                        q_repo = PlayerInfoQueueRepository(session)
                                        await q_repo.mark_failed(job.id, str(exc))
                                        await session.commit()
                                except Exception as mark_err:
                                    worker_labels[worker_id] = (
                                        f"[bold red]FAILED mark job {job.id}: "
                                        f"{escape(str(mark_err))}[/bold red]"
                                    )
                            else:
                                worker_labels[worker_id] = (
                                    "[bold orange1]WARNING retrying"
                                    f" ({attempt}/3)[/bold orange1]"
                                )
                                await asyncio.sleep(2)

                    if browser_restart:
                        break

                    if not success:
                        worker_labels[worker_id] = (
                            f"[bold red]FAILED job {job.id}"
                            " — exhausted retries[/bold red]"
                        )

        except Exception:
            if not browser_started:
                restart_count += 1
                if restart_count >= max_restarts:
                    worker_labels[worker_id] = (
                        "[bold red]browser failed — giving up[/bold red]"
                    )
                    return processed
                msg = (
                    "[bold red]browser start failed"
                    f" — retry {restart_count}/{max_restarts}[/bold red]"
                )
                worker_labels[worker_id] = msg
                await asyncio.sleep(10)
                continue
            worker_labels[worker_id] = (
                "[bold red]unexpected error — restarting[/bold red]"
            )
            await asyncio.sleep(5)
            continue


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
        args = parser.parse_args()
        if workers is None:
            workers = args.workers
        if seed is None:
            seed = args.seed

    settings = Settings()  # type: ignore[call-arg]

    assert workers is not None
    settings.db.pool_size = max(workers * 2, settings.db.pool_size)

    session_factory = create_session_factory(settings.db)

    # Recover any stale IN_PROGRESS rows from a previous interrupted run
    async with get_session(session_factory) as session:
        queue_repo = PlayerInfoQueueRepository(session)
        stale = await queue_repo.recover_stale()
        await session.commit()
    if stale:
        logger.info("Recovered %d stale jobs back to PENDING", stale)

    # Recover any permanently FAILED rows so they are retried this run
    async with get_session(session_factory) as session:
        queue_repo = PlayerInfoQueueRepository(session)
        failed = await queue_repo.recover_failed()
        await session.commit()
    if failed:
        logger.info("Recovered %d failed jobs back to PENDING", failed)

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

    worker_labels: dict[int, str] = {}
    worker_counts: dict[int, int] = {}
    stop_event = asyncio.Event()

    t0 = time.monotonic()
    with Live(
        _build_table(
            worker_labels,
            worker_counts,
            workers,
            already_done,
            already_done + pending_total,
        ),
        console=_console,
        refresh_per_second=2,
    ) as live:
        display_task = asyncio.create_task(
            _display_loop(
                workers,
                worker_labels,
                worker_counts,
                already_done,
                already_done + pending_total,
                stop_event,
                live,
            )
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
                    worker_labels=worker_labels,
                    worker_counts=worker_counts,
                    fbref_base_url=settings.scraping.fbref_base_url,
                )
                for i in range(workers)
            ],
            return_exceptions=True,
        )
        stop_event.set()
        await display_task
    elapsed = time.monotonic() - t0
    total = sum(r for r in results if isinstance(r, int))
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
