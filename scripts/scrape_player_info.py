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
from typing import Any

import sqlalchemy as sa
from pydoll.exceptions import BrowserException
from rich.console import Console
from rich.live import Live
from rich.markup import escape
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config.settings import Settings
from core.application.base_worker import BaseWorker, CooldownRequired
from core.application.scrape_job_processor import ScrapeJobProcessor
from core.exceptions.scraper import PageLoadError, RateLimitError
from infrastructure.browser.pydoll_engine import PydollEngine
from infrastructure.display.worker_display import build_worker_table, run_display_loop
from infrastructure.persistence.models.scrape_queue import ScrapeQueue, ScrapeStatus
from infrastructure.persistence.models.shared.player import Player
from infrastructure.persistence.repositories.player_info import PlayerInfoRepository
from infrastructure.persistence.repositories.player_info_queue import (
    PlayerInfoQueueRepository,
)
from infrastructure.persistence.session import create_session_factory, get_session
from infrastructure.scraping.player_info import PlayerInfoScraper

_console = Console()


class _NotificationBuffer:
    """Thread-safe store for log messages with a TTL (default 5 s).

    Messages older than *ttl* seconds are silently dropped on the next read.
    """

    def __init__(self, ttl: float = 5.0) -> None:
        self._entries: list[tuple[float, str]] = []
        self._ttl = ttl

    def add(self, msg: str) -> None:
        self._entries.append((time.monotonic(), msg))

    def active(self) -> list[str]:
        now = time.monotonic()
        self._entries = [(t, m) for t, m in self._entries if now - t < self._ttl]
        return [m for _, m in self._entries]


class _BufferHandler(logging.Handler):
    """Logging handler that routes records into a _NotificationBuffer."""

    def __init__(self, buf: _NotificationBuffer) -> None:
        super().__init__()
        self._buf = buf

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._buf.add(self.format(record))
        except Exception:
            self.handleError(record)


_notifications = _NotificationBuffer(ttl=5.0)

_buf_handler = _BufferHandler(_notifications)
_buf_handler.setFormatter(logging.Formatter("%(levelname)s  %(message)s"))

_root_logger = logging.getLogger()
_root_logger.handlers.clear()
_root_logger.addHandler(_buf_handler)
_root_logger.setLevel(logging.WARNING)

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
# Worker class
# ---------------------------------------------------------------------------


class PlayerInfoWorker(BaseWorker["ScrapeQueue"]):
    """Worker that processes player_info jobs from scrape_queue until empty."""

    def __init__(
        self,
        worker_id: int,
        session_factory: async_sessionmaker[AsyncSession],
        fetch_gate: asyncio.Semaphore,
        profile_base: str,
        worker_labels: dict[int, str],
        worker_counts: dict[int, int],
        position_cache: dict[str, int],
        valid_countries: frozenset[str],
        country_name_cache: dict[str, str],
        fbref_base_url: str = "https://fbref.com",
        step2_done: asyncio.Event | None = None,
    ) -> None:
        super().__init__(
            worker_id=worker_id,
            session_factory=session_factory,
            fetch_gate=fetch_gate,
            profile_base=profile_base,
            worker_labels=worker_labels,
            worker_counts=worker_counts,
        )
        self._position_cache = position_cache
        self._valid_countries = valid_countries
        self._country_name_cache = country_name_cache
        self._fbref_base_url = fbref_base_url
        self._step2_done = step2_done

    @property
    def profile_dir(self) -> str:
        return f"{self._profile_base}-{self._worker_id}"

    @property
    def engine_name(self) -> str:
        return f"Crawl-{self._worker_id}"

    def _build_engine(self) -> PydollEngine:
        return PydollEngine(profile_dir=self.profile_dir, name=self.engine_name)

    async def startup_delay(self) -> None:
        delay = self._worker_id * random.uniform(1.5, 3.0)
        self._labels[self._worker_id] = f"Waiting {delay:.1f}s before start..."
        await asyncio.sleep(delay)

    async def run_claim_loop(self, engine: Any) -> bool:
        """Process player_info jobs for one browser session.

        Returns True when queue is empty and step2 is done (stop).
        Returns False on BrowserException (restart browser).
        """
        self._labels[self._worker_id] = "Starting crawl..."

        while True:
            async with get_session(self._session_factory) as session:
                queue_repo = PlayerInfoQueueRepository(session)
                job = await queue_repo.claim_next()
                await session.commit()

            if job is None:
                if self._step2_done is None or self._step2_done.is_set():
                    return True
                self._labels[self._worker_id] = "[dim]Waiting for step 2...[/]"
                await asyncio.sleep(10)
                continue

            attempt = 0
            success = False
            browser_restart = False

            while attempt < 3 and not success:
                try:
                    async with self._fetch_gate:
                        await engine.navigate(self._fbref_base_url + job.url)
                        await asyncio.sleep(random.uniform(2.0, 6.0))
                    # Challenge polling and cooldown run outside gate so other
                    # workers are not blocked during Cloudflare resolution.
                    html = await engine.wait_for_challenge(
                        self._fbref_base_url + job.url
                    )
                    await asyncio.sleep(random.uniform(3, 10))
                    if not html:
                        raise PageLoadError(
                            "empty HTML response",
                            url=self._fbref_base_url + job.url,
                        )

                    scraper = PlayerInfoScraper(
                        player_id=_player_id_from_url(job.url),
                        player_info_url=job.url,
                    )

                    async with get_session(self._session_factory) as session:
                        info_repo = PlayerInfoRepository(session)
                        q_repo = PlayerInfoQueueRepository(session)
                        processor = ScrapeJobProcessor(
                            scraper=scraper,
                            queue_repo=q_repo,
                            player_info_repo=info_repo,
                            country_name_cache=self._country_name_cache,
                            position_cache=self._position_cache,
                            valid_countries=self._valid_countries,
                        )
                        result = await processor.process(  # type: ignore[arg-type]
                            job, html
                        )
                        await session.commit()

                    success = True
                    self._processed += 1
                    self._counts[self._worker_id] = self._processed
                    full_name = result[0] if result else "unknown"
                    self._labels[self._worker_id] = escape(full_name or "unknown")

                except (
                    PageLoadError, RateLimitError, BrowserException
                ) as exc:
                    attempt += 1
                    if isinstance(exc, BrowserException):
                        self._labels[self._worker_id] = (
                            "[bold red]ERROR[/] Browser error — Restarting"
                        )
                        try:
                            async with get_session(self._session_factory) as session:
                                q_repo = PlayerInfoQueueRepository(session)
                                await q_repo.mark_failed(job.id, str(exc))
                                await session.commit()
                        except Exception as mark_err:
                            logger.error(
                                "[worker-%d] mark_failed error: %s",
                                self._worker_id, mark_err,
                            )
                        browser_restart = True
                        break
                    is_terminal = attempt >= 3
                    if is_terminal:
                        self._labels[self._worker_id] = (
                            f"[bold red]FAILED[/] Job {job.id} — {escape(str(exc))}"
                        )
                        try:
                            async with get_session(self._session_factory) as session:
                                q_repo = PlayerInfoQueueRepository(session)
                                await q_repo.mark_failed(job.id, str(exc))
                                await session.commit()
                        except Exception as mark_err:
                            logger.error(
                                "[worker-%d] failed to mark job %d as failed: %s",
                                self._worker_id, job.id, mark_err,
                            )
                    else:
                        self._labels[self._worker_id] = (
                            f"[bold yellow]WARNING[/] Retrying ({attempt}/3)"
                        )
                        await asyncio.sleep(random.uniform(5.0, 15.0))

            if browser_restart:
                return False

            if not success:
                self._labels[self._worker_id] = (
                    f"[bold red]FAILED[/] Job {job.id} — max retries reached"
                )
                raise CooldownRequired


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
        stale = await queue_repo.recover_all_stale()
        await session.commit()
    if stale:
        logger.debug("Resumed: %d interrupted jobs restored to queue", stale)

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

    fetch_gate = asyncio.Semaphore(2)

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
        build_worker_table(
            worker_labels,
            worker_counts,
            workers,
            already_done,
            already_done + pending_total,
        ),
        console=_console,
        refresh_per_second=2,
        vertical_overflow="crop",
    ) as live:
        display_task = asyncio.create_task(
            run_display_loop(
                workers,
                worker_labels,
                worker_counts,
                already_done,
                already_done + pending_total,
                stop_event,
                live,
                _notifications.active,
            )
        )
        results = await asyncio.gather(
            *[
                PlayerInfoWorker(
                    worker_id=i + 1,
                    session_factory=session_factory,
                    fetch_gate=fetch_gate,
                    profile_base=settings.scraping.chrome_profile_dir,
                    worker_labels=worker_labels,
                    worker_counts=worker_counts,
                    position_cache=position_cache,
                    valid_countries=valid_countries,
                    country_name_cache=country_name_cache,
                    fbref_base_url=settings.scraping.fbref_base_url,
                ).run()
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
