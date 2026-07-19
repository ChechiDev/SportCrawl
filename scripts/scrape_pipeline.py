"""Pipeline orchestrator — runs step 2 (scrape_players) and step 3 (scrape_player_info)
concurrently.

Step 3 starts automatically while step 2 is still running, triggered by a configurable
pending-job threshold in the player_info queue.

Usage:
    uv run python scripts/scrape_pipeline.py --workers 5
            uv run python scripts/scrape_pipeline.py --workers 5 \
            --trigger-count 50 --trigger-delay 120
    uv run python scripts/scrape_pipeline.py --workers 3 --all
"""

from __future__ import annotations

import argparse
import asyncio
import logging

import sqlalchemy as sa
from rich.console import Console, Group
from rich.live import Live
from rich.logging import RichHandler
from rich.markup import escape
from rich.table import Table
from rich.text import Text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config.settings import Settings
from infrastructure.persistence.repositories.player_info_queue import (
    PlayerInfoQueueRepository,
)
from infrastructure.persistence.repositories.player_list_queue import (
    PlayerListQueueRepository,
)
from infrastructure.persistence.session import create_session_factory, get_session
from scripts.scrape_player_info import _load_country_ids, _load_country_name_cache
from scripts.scrape_player_info import _seed_queue as _seed_player_info_queue
from scripts.scrape_player_info import _worker as _player_info_worker
from scripts.scrape_players import _load_all_countries
from scripts.scrape_players import _seed_queue as _seed_player_list_queue
from scripts.scrape_players import _worker as _player_list_worker

# force=True resets any handlers set by scrape_players / scrape_player_info at
# import time so all log output routes through the single Live-display console.
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
        )
    ],
    force=True,
)
for _noisy in ("pydoll", "websockets", "asyncio"):
    logging.getLogger(_noisy).setLevel(logging.CRITICAL)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Unified display
# ---------------------------------------------------------------------------


def _build_unified_display(
    s2_labels: dict[int, str],
    s2_counts: dict[int, int],
    s2_workers: int,
    s2_total: int,
    s3_labels: dict[int, str],
    s3_counts: dict[int, int],
    s3_workers: int,
    s3_total: int,
    s3_ready: bool,
) -> Group:
    # --- Step 2 ---
    s2_done = sum(s2_counts.values())
    s2_total_str = f"{s2_done}/{s2_total}" if s2_total else str(s2_done)

    s2_header = Text.assemble(
        ("Step ", "bold"),
        ("2", "bold cyan"),
        (" — Scraping Players", "bold"),
    )
    s2_table = Table.grid(padding=(0, 2))
    s2_table.add_column(style="bold green")
    s2_table.add_column()
    for i in range(1, s2_workers + 1):
        own = s2_counts.get(i, 0)
        label = s2_labels.get(i, "starting crawl...")
        row = f"[Crawl-{i}] [{own} | {s2_total_str}] {label}"
        s2_table.add_row("RUN", escape(row))

    # --- Step 3 ---
    s3_done = sum(s3_counts.values())
    s3_total_str = f"{s3_done}/{s3_total}" if s3_total else str(s3_done)

    s3_suffix = "" if s3_ready else "  [waiting for trigger...]"
    s3_header = Text.assemble(
        ("Step ", "bold"),
        ("3", "bold cyan"),
        (f" — Scraping Single player info{s3_suffix}", "bold"),
    )
    if s3_ready:
        s3_table = Table.grid(padding=(0, 2))
        s3_table.add_column(style="bold green")
        s3_table.add_column()
        for i in range(1, s3_workers + 1):
            own = s3_counts.get(i, 0)
            label = s3_labels.get(i, "starting crawl...")
            row = f"[Crawl-{i}] [{own} | {s3_total_str}] {label}"
            s3_table.add_row("RUN", escape(row))
        return Group(s2_header, s2_table, Text(""), s3_header, s3_table)

    return Group(s2_header, s2_table, Text(""), s3_header)


async def _s3_total_poller(
    session_factory: async_sessionmaker[AsyncSession],
    s3_total_ref: list[int],
    stop_event: asyncio.Event,
) -> None:
    """Refresh s3_total_ref[0] every 5s from the live scrape_queue count."""
    while not stop_event.is_set():
        await asyncio.sleep(5)
        async with get_session(session_factory) as session:
            result = await session.execute(
                sa.text(
                    "SELECT count(*) FROM sch_infra.scrape_queue"
                    " WHERE job_type='player_info'"
                )
            )
            s3_total_ref[0] = int(result.scalar() or 0)


async def _display_loop(
    s2_labels: dict[int, str],
    s2_counts: dict[int, int],
    s2_workers: int,
    s2_total: int,
    s3_labels: dict[int, str],
    s3_counts: dict[int, int],
    s3_workers: int,
    s3_total_ref: list[int],
    s3_ready_event: asyncio.Event,
    stop_event: asyncio.Event,
    live: Live,
) -> None:
    while not stop_event.is_set():
        renderable = _build_unified_display(
            s2_labels, s2_counts, s2_workers, s2_total,
            s3_labels, s3_counts, s3_workers, s3_total_ref[0],
            s3_ready_event.is_set(),
        )
        live.update(renderable)
        await asyncio.sleep(0.5)
    renderable = _build_unified_display(
        s2_labels, s2_counts, s2_workers, s2_total,
        s3_labels, s3_counts, s3_workers, s3_total_ref[0],
        s3_ready_event.is_set(),
    )
    live.update(renderable)


# ---------------------------------------------------------------------------
# Trigger watcher
# ---------------------------------------------------------------------------


async def _player_info_reseeder(
    session_factory: async_sessionmaker[AsyncSession],
    step2_done: asyncio.Event,
) -> None:
    """Re-seed player_info queue every 30s while step 2 is still running.

    Step 2 continuously adds new players to tbl_players. Without periodic
    re-seeding, step 3 workers exhaust the initial seed and stall waiting for
    step 2 to finish even though new jobs are available.
    """
    while not step2_done.is_set():
        await asyncio.sleep(30)
        await _seed_player_info_queue(session_factory)
    # Final seed after step 2 completes so no player is missed.
    await _seed_player_info_queue(session_factory)


async def _trigger_watcher(
    session_factory: async_sessionmaker[AsyncSession],
    trigger_count: int,
    step3_ready: asyncio.Event,
    step2_done: asyncio.Event,
) -> None:
    """Poll tbl_players every 5s until scraped player count >= trigger_count.

    Also fires immediately when step2_done is set (all step-2 workers finished),
    so step-3 workers don't wait forever when the queue is small.
    """
    poll_interval = 5.0

    while not step3_ready.is_set():
        if step2_done.is_set():
            step3_ready.set()
            return

        async with get_session(session_factory) as session:
            result = await session.execute(
                sa.text("SELECT count(*) FROM sch_shared.tbl_players")
            )
            players = int(result.scalar() or 0)

        if players >= trigger_count:
            step3_ready.set()
            return

        await asyncio.sleep(poll_interval)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


async def main(
    workers: int = 1,
    trigger_count: int = 100,
    all_countries: bool = False,
) -> None:
    settings = Settings()  # type: ignore[call-arg]
    pool_size = max(workers * 8, settings.db.pool_size)
    settings.db.pool_size = pool_size
    session_factory = create_session_factory(settings.db)

    # --- Seed and recover step 2 ---
    if all_countries:
        countries = await _load_all_countries(session_factory)
    else:
        # Default: seed nothing (assume queue already populated).
        # If no --all flag, users rely on existing queue state.
        countries = []

    s2_total = 0
    if countries:
        await _seed_player_list_queue(session_factory, countries)
        s2_total = len(countries)

    async with get_session(session_factory) as session:
        stale = await PlayerListQueueRepository(session).recover_stale()
        await session.commit()
    if stale:
        logger.info("Recovered %d stale player_list jobs back to PENDING", stale)

    # Count actual pending step-2 jobs (covers the case where --all was not passed
    # but jobs already exist in the queue).
    if not s2_total:
        async with get_session(session_factory) as session:
            result = await session.execute(
                sa.text(
                    "SELECT count(*) FROM sch_infra.scrape_queue"
                    " WHERE job_type='player_list' AND status='PENDING'"
                )
            )
            s2_total = int(result.scalar() or 0)

    # Count existing step-3 total for display denominator
    async with get_session(session_factory) as session:
        result = await session.execute(
            sa.text(
                "SELECT count(*) FROM sch_infra.scrape_queue"
                " WHERE job_type='player_info' AND status IN ('PENDING','IN_PROGRESS')"
            )
        )
        s3_queue_count = int(result.scalar() or 0)
        result = await session.execute(
            sa.text("SELECT count(*) FROM sch_shared.tbl_player_info")
        )
        s3_already_done = int(result.scalar() or 0)
    s3_total = s3_already_done + s3_queue_count

    # Shared caches for step-3 workers
    valid_countries = await _load_country_ids(session_factory)
    country_name_cache = await _load_country_name_cache(session_factory)
    position_cache: dict[str, int] = {}

    # Events
    step2_done: asyncio.Event = asyncio.Event()
    step3_ready: asyncio.Event = asyncio.Event()

    # Shared display state
    s2_labels: dict[int, str] = {}
    s2_counts: dict[int, int] = {}
    s3_labels: dict[int, str] = {}
    s3_counts: dict[int, int] = {}
    stop_event: asyncio.Event = asyncio.Event()

    # Separate fetch gates — step 2 and step 3 hit different URLs
    s2_fetch_gate = asyncio.Semaphore(1)
    s3_fetch_gate = asyncio.Semaphore(1)

    s3_total_ref: list[int] = [s3_total]

    initial_renderable = _build_unified_display(
        s2_labels, s2_counts, workers, s2_total,
        s3_labels, s3_counts, workers, s3_total_ref[0],
        False,
    )

    with Live(initial_renderable, console=_console, refresh_per_second=2) as live:
        display_task = asyncio.create_task(
            _display_loop(
                s2_labels, s2_counts, workers, s2_total,
                s3_labels, s3_counts, workers, s3_total_ref,
                step3_ready, stop_event, live,
            )
        )

        poller_task = asyncio.create_task(
            _s3_total_poller(session_factory, s3_total_ref, stop_event)
        )

        trigger_task = asyncio.create_task(
            _trigger_watcher(
                session_factory, trigger_count,
                step3_ready, step2_done,
            )
        )

        # --- Step 2 workers — run as background tasks so step 3 can start mid-way ---
        s2_tasks = [
            asyncio.create_task(
                _player_list_worker(
                    worker_id=i + 1,
                    session_factory=session_factory,
                    fetch_gate=s2_fetch_gate,
                    profile_base=settings.scraping.chrome_profile_dir,
                    settings=settings,
                    worker_labels=s2_labels,
                    worker_counts=s2_counts,
                )
            )
            for i in range(workers)
        ]

        # --- Wait for trigger (tbl_players count >= trigger_count) ---
        await step3_ready.wait()

        async with get_session(session_factory) as session:
            stale3 = await PlayerInfoQueueRepository(session).recover_stale()
            await session.commit()
        if stale3:
            logger.info("Recovered %d stale player_info jobs back to PENDING", stale3)

        # Seed step-3 queue from tbl_players (idempotent)
        await _seed_player_info_queue(session_factory)

        # Refresh total for display after seeding
        async with get_session(session_factory) as session:
            result = await session.execute(
                sa.text(
                    "SELECT count(*) FROM sch_infra.scrape_queue"
                    " WHERE job_type='player_info'"
                )
            )
            s3_total_ref[0] = int(result.scalar() or 0)

        # Re-seed every 30s so step 3 workers pick up players added by step 2
        # while it is still running (without this, workers stall on empty queue).
        reseeder_task = asyncio.create_task(
            _player_info_reseeder(session_factory, step2_done)
        )

        # --- Step 3 workers — run concurrently with remaining step 2 work ---
        s3_tasks = [
            asyncio.create_task(
                _player_info_worker(
                    worker_id=i + 1,
                    session_factory=session_factory,
                    fetch_gate=s3_fetch_gate,
                    chrome_profile_base=settings.scraping.chrome_profile_dir,
                    position_cache=position_cache,
                    valid_countries=valid_countries,
                    country_name_cache=country_name_cache,
                    worker_labels=s3_labels,
                    worker_counts=s3_counts,
                    fbref_base_url=settings.scraping.fbref_base_url,
                    step2_done=step2_done,
                )
            )
            for i in range(workers)
        ]

        # Wait for step 2, signal done, let reseeder do its final seed, drain step 3
        s2_results = await asyncio.gather(*s2_tasks, return_exceptions=True)
        step2_done.set()
        await reseeder_task  # waits for final seed after step2_done is set
        s3_results = await asyncio.gather(*s3_tasks, return_exceptions=True)

        trigger_task.cancel()
        poller_task.cancel()
        await asyncio.gather(trigger_task, poller_task, return_exceptions=True)
        stop_event.set()
        await display_task

    s2_grand = sum(r for r in s2_results if isinstance(r, int))
    s3_grand = sum(r for r in s3_results if isinstance(r, int))
    logger.info(
        "Pipeline done. step2=%d jobs | step3=%d jobs | workers=%d",
        s2_grand, s3_grand, workers,
    )


def run() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Pipeline: scrape players (step 2) then player info (step 3) "
            "concurrently."
        )
    )
    parser.add_argument(
        "--workers",
        metavar="N",
        type=int,
        default=1,
        help="Number of parallel workers per step (default: 1).",
    )
    parser.add_argument(
        "--trigger-count",
        metavar="N",
        type=int,
        default=100,
        help="Minimum players in tbl_players before step 3 starts (default: 100).",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        dest="all_countries",
        help="Seed all countries from the database into the player_list queue.",
    )
    args = parser.parse_args()

    asyncio.run(
        main(
            workers=args.workers,
            trigger_count=args.trigger_count,
            all_countries=args.all_countries,
        )
    )


if __name__ == "__main__":
    run()
