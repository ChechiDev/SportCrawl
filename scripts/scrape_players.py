"""Player discovery scraper — single country or all countries.

Usage:
    uv run python scripts/scrape_players.py                  # Spain (default)
    uv run python scripts/scrape_players.py --country ARG
    uv run python scripts/scrape_players.py --url <FBREF_COUNTRY_PLAYERS_URL>
    uv run python scripts/scrape_players.py --all            # all 219 countries from DB
    uv run python scripts/scrape_players.py --all --workers 3
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re

import sqlalchemy as sa
from rich.console import Console, Group
from rich.live import Live
from rich.logging import RichHandler
from rich.markup import escape
from rich.table import Table
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config.settings import Settings
from infrastructure.browser.pydoll_engine import PydollEngine
from infrastructure.persistence.models.scrape_queue import ScrapeQueue, ScrapeStatus
from infrastructure.persistence.models.shared.country import Country
from infrastructure.persistence.repositories.player_list_queue import (
    PlayerListQueueRepository,
)
from infrastructure.persistence.session import create_session_factory, get_session
from infrastructure.scraping.players import PlayerListScraper

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

_FBREF_BASE = "https://fbref.com"
_BASE_URL = "https://fbref.com/en/country/players/{code}/{code}-Football"
_COUNTRY_CODE_RE = re.compile(r"/en/country/players/([A-Za-z]{2,3})/", re.IGNORECASE)

COUNTRY_URLS: dict[str, str] = {
    "ESP": "https://fbref.com/en/country/players/ESP/Spain-Football",
    "ARG": "https://fbref.com/en/country/players/ARG/Argentina-Football",
    "BRA": "https://fbref.com/en/country/players/BRA/Brazil-Football",
    "FRA": "https://fbref.com/en/country/players/FRA/France-Football",
    "ENG": "https://fbref.com/en/country/players/ENG/England-Football",
}


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
        label = worker_labels.get(i, "Starting crawl...")
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


def _players_url(country_url: str) -> str:
    """Derive player-list URL from country_url stored in DB.

    /en/country/AFG/Afghanistan-Football
    → https://fbref.com/en/country/players/AFG/Afghanistan-Football
    """
    path = country_url.replace("/en/country/", "/en/country/players/", 1)
    return f"{_FBREF_BASE}{path}"


async def _load_all_countries(
    session_factory: async_sessionmaker[AsyncSession],
) -> list[tuple[str, str]]:
    """Return (country_id, player_list_url) for every country in the DB."""
    async with get_session(session_factory) as session:
        result = await session.execute(
            sa.select(Country.country_id, Country.country_url)
            .order_by(Country.country_name)
        )
        return [(row.country_id, _players_url(row.country_url)) for row in result]


async def _seed_queue(
    session_factory: async_sessionmaker[AsyncSession],
    countries: list[tuple[str, str]],
) -> int:
    """Bulk-insert one scrape_queue row per country URL with job_type='player_list'.

    ON CONFLICT DO NOTHING keeps the operation idempotent across restarts.

    Returns:
        Number of newly inserted rows (0 when all URLs already queued).
    """
    if not countries:
        return 0

    rows = [
        {
            "url": url,
            "domain": "fbref.com",
            "status": ScrapeStatus.PENDING,
            "job_type": "player_list",
        }
        for _, url in countries
    ]

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

    return inserted


async def _worker(
    worker_id: int,
    session_factory: async_sessionmaker[AsyncSession],
    fetch_gate: asyncio.Semaphore,
    profile_base: str,
    settings: Settings,
    worker_labels: dict[int, str],
    worker_counts: dict[int, int],
) -> int:
    """Drain player_list scrape_queue jobs until empty.

    Each call gets its own isolated Chrome profile. Jobs are claimed atomically
    via SELECT FOR UPDATE SKIP LOCKED. The fetch_gate semaphore ensures at most
    one FBRef HTTP request is in flight across all workers.

    Returns:
        Number of jobs successfully processed.
    """
    profile_dir = f"{profile_base}-player-list-{worker_id}"
    processed = 0

    max_restarts = 5
    restart_count = 0
    while True:
        browser_started = False
        try:
            async with PydollEngine(
                profile_dir=profile_dir, name=f"PlayerList-{worker_id}"
            ) as engine:
                browser_started = True
                restart_count = 0  # reset on successful start
                scraper = PlayerListScraper(engine, settings.scraping, session_factory)

                while True:
                    async with get_session(session_factory) as session:
                        job = await PlayerListQueueRepository(session).claim_next()
                        await session.commit()

                    if job is None:
                        return processed

                    country_match = _COUNTRY_CODE_RE.search(job.url)
                    country_code = (
                        country_match.group(1).upper()
                        if country_match
                        else job.url
                    )

                    from pydoll.exceptions import BrowserException as _BrowserException

                    max_attempts = 3
                    browser_restart = False
                    for attempt in range(1, max_attempts + 1):
                        try:
                            async with fetch_gate:
                                page, _ = await scraper.scrape(job.url)

                            async with get_session(session_factory) as session:
                                repo = PlayerListQueueRepository(session)
                                await repo.mark_done(job.id)
                                await session.commit()

                            processed += 1
                            worker_counts[worker_id] = processed
                            total_players = len(page.players)
                            worker_labels[worker_id] = f"{country_code}: {total_players:,} players"  # noqa: E501
                            break

                        except Exception as exc:
                            if isinstance(exc, _BrowserException):
                                worker_labels[worker_id] = (
                                    "[bold red]BROWSER ERROR — restarting[/bold red]"
                                )
                                try:
                                    async with get_session(session_factory) as session:
                                        repo = PlayerListQueueRepository(session)
                                        await repo.mark_failed(job.id, str(exc))
                                        await session.commit()
                                except Exception:
                                    pass
                                browser_restart = True
                                break

                            if attempt < max_attempts:
                                lbl = (
                                    f"[bold orange1]RETRY {attempt}/{max_attempts}"
                                    f" — {country_code}[/bold orange1]"
                                )
                                worker_labels[worker_id] = lbl
                                await asyncio.sleep(2)
                            else:
                                try:
                                    async with get_session(session_factory) as session:
                                        repo = PlayerListQueueRepository(session)
                                        await repo.mark_failed(job.id, str(exc))
                                        await session.commit()
                                except Exception:
                                    pass
                                worker_labels[worker_id] = (
                                    f"[bold red]FAILED — {country_code}[/bold red]"
                                )

                    if browser_restart:
                        break

        except Exception:
            if not browser_started:
                restart_count += 1
                if restart_count >= max_restarts:
                    worker_labels[worker_id] = (
                        "[bold red]BROWSER FAILED — giving up[/bold red]"
                    )
                    return processed
                msg = (
                    f"[bold red]BROWSER START FAILED"
                    f" — retry {restart_count}/{max_restarts}[/bold red]"
                )
                worker_labels[worker_id] = msg
                await asyncio.sleep(10)
                continue
            worker_labels[worker_id] = (
                "[bold red]UNEXPECTED ERROR — restarting[/bold red]"
            )
            await asyncio.sleep(5)
            continue


async def scrape_one(scraper: PlayerListScraper, url: str) -> int:
    _, inserted = await scraper.scrape(url)
    return inserted


async def main_single(url: str, verbose: bool = True) -> int:
    settings = Settings()  # type: ignore[call-arg]
    session_factory = create_session_factory(settings.db)
    async with PydollEngine() as engine:
        scraper = PlayerListScraper(engine, settings.scraping, session_factory)
        page, inserted = await scraper.scrape(url)

        if verbose:
            print(f"\ncountry_id : {page.country_id}")
            print(f"players    : {len(page.players)}")
            print(f"inserted   : {inserted}")
            print("\nFirst 10:")
            for p in page.players[:10]:
                career = f"{p.career_start}–{p.career_end}"
                print(f"  {p.player_id}  {p.full_name:<30}  {career}")

        return inserted


async def main_all(workers: int = 1) -> None:
    settings = Settings()  # type: ignore[call-arg]
    settings.db.pool_size = max(workers * 2, settings.db.pool_size)
    session_factory = create_session_factory(settings.db)

    countries = await _load_all_countries(session_factory)
    total = len(countries)
    logger.info("Seeding %d countries into queue…", total)

    await _seed_queue(session_factory, countries)

    async with get_session(session_factory) as session:
        stale = await PlayerListQueueRepository(session).recover_stale()
        await session.commit()
    if stale:
        logger.info("Recovered %d stale player_list jobs back to PENDING", stale)

    fetch_gate = asyncio.Semaphore(1)
    logger.info("Launching %d worker(s)…", workers)

    worker_labels: dict[int, str] = {}
    worker_counts: dict[int, int] = {}
    stop_event = asyncio.Event()

    with Live(
        _build_table(worker_labels, worker_counts, workers, 0, total),
        console=_console,
        refresh_per_second=2,
    ) as live:
        display_task = asyncio.create_task(
            _display_loop(
                workers, worker_labels, worker_counts, 0, total, stop_event, live
            )
        )
        results = await asyncio.gather(
            *[
                _worker(
                    worker_id=i + 1,
                    session_factory=session_factory,
                    fetch_gate=fetch_gate,
                    profile_base=settings.scraping.chrome_profile_dir,
                    settings=settings,
                    worker_labels=worker_labels,
                    worker_counts=worker_counts,
                )
                for i in range(workers)
            ],
            return_exceptions=True,
        )
        stop_event.set()
        await display_task

    grand_total = sum(r for r in results if isinstance(r, int))
    logger.info("Done. %d jobs processed across %d worker(s).", grand_total, workers)


async def main_countries(codes: list[str], workers: int = 1) -> None:
    if not codes:
        logger.warning("main_countries called with empty codes list — nothing to do")
        return

    countries = [(code, _BASE_URL.format(code=code)) for code in codes]
    total = len(countries)
    workers = total

    settings = Settings()  # type: ignore[call-arg]
    settings.db.pool_size = max(workers * 2, settings.db.pool_size)
    session_factory = create_session_factory(settings.db)

    await _seed_queue(session_factory, countries)

    async with get_session(session_factory) as session:
        stale = await PlayerListQueueRepository(session).recover_stale()
        await session.commit()
    if stale:
        logger.info("Recovered %d stale player_list jobs back to PENDING", stale)

    fetch_gate = asyncio.Semaphore(1)

    worker_labels: dict[int, str] = {}
    worker_counts: dict[int, int] = {}
    stop_event = asyncio.Event()

    with Live(
        _build_table(worker_labels, worker_counts, workers, 0, total),
        console=_console,
        refresh_per_second=2,
    ) as live:
        display_task = asyncio.create_task(
            _display_loop(
                workers, worker_labels, worker_counts, 0, total, stop_event, live
            )
        )
        results = await asyncio.gather(
            *[
                _worker(
                    worker_id=i + 1,
                    session_factory=session_factory,
                    fetch_gate=fetch_gate,
                    profile_base=settings.scraping.chrome_profile_dir,
                    settings=settings,
                    worker_labels=worker_labels,
                    worker_counts=worker_counts,
                )
                for i in range(workers)
            ],
            return_exceptions=True,
        )
        stop_event.set()
        await display_task

    grand_total = sum(r for r in results if isinstance(r, int))
    logger.info("Done. %d jobs processed across %d worker(s).", grand_total, workers)


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape FBRef player lists.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--country",
        metavar="CODE",
        default="ESP",
        help="FBRef country code (default: ESP).",
    )
    group.add_argument(
        "--url", metavar="URL", help="Full FBRef country player-list URL."
    )
    group.add_argument("--all", action="store_true", dest="all_countries",
                       help="Scrape all countries from the database.")
    parser.add_argument(
        "--workers",
        metavar="N",
        type=int,
        default=1,
        help="Number of parallel workers (default: 1).",
    )
    args = parser.parse_args()

    if args.all_countries:
        asyncio.run(main_all(workers=args.workers))
    else:
        target_url = args.url or COUNTRY_URLS.get(
            args.country.upper(),
            _BASE_URL.format(code=args.country.upper()),
        )
        asyncio.run(main_single(target_url))


if __name__ == "__main__":
    main()
