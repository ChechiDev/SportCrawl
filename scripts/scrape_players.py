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
from typing import Any

import sqlalchemy as sa
from rich.console import Console
from rich.live import Live
from rich.text import Text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config.settings import Settings
from core.application.base_worker import BaseWorker
from infrastructure.browser.pydoll_engine import PydollEngine
from infrastructure.display.worker_display import build_worker_table, run_display_loop
from infrastructure.persistence.models.scrape_queue import ScrapeQueue, ScrapeStatus
from infrastructure.persistence.models.shared.country import Country
from infrastructure.persistence.repositories.player_list_queue import (
    PlayerListQueueRepository,
)
from infrastructure.persistence.session import create_session_factory, get_session
from infrastructure.scraping.players import PlayerListScraper

_console = Console()

_root_logger = logging.getLogger()
_root_logger.handlers.clear()
_root_logger.setLevel(logging.CRITICAL)

for _noisy in (
    "pydoll", "websockets", "asyncio", "ports", "ports.scraper", "infrastructure"
):
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


class PlayerListWorker(BaseWorker["ScrapeQueue"]):
    """Worker that drains player_list scrape_queue jobs until the queue is empty."""

    def __init__(
        self,
        worker_id: int,
        session_factory: async_sessionmaker[AsyncSession],
        fetch_gate: asyncio.Semaphore,
        profile_base: str,
        worker_labels: dict[int, str],
        worker_counts: dict[int, int],
        settings: Settings,
        url_to_name: dict[str, str] | None = None,
        code_to_name: dict[str, str] | None = None,
    ) -> None:
        super().__init__(
            worker_id=worker_id,
            session_factory=session_factory,
            fetch_gate=fetch_gate,
            profile_base=profile_base,
            worker_labels=worker_labels,
            worker_counts=worker_counts,
        )
        self._settings = settings
        self._url_to_name = url_to_name or {}
        self._code_to_name = code_to_name or {}
        self._scraper: PlayerListScraper | None = None

    @property
    def profile_dir(self) -> str:
        return f"{self._profile_base}-player-list-{self._worker_id}"

    @property
    def engine_name(self) -> str:
        return f"PlayerList-{self._worker_id}"

    def _build_engine(self) -> PydollEngine:
        return PydollEngine(profile_dir=self.profile_dir, name=self.engine_name)

    async def on_browser_ready(self, engine: Any) -> None:
        self._scraper = PlayerListScraper(
            engine, self._settings.scraping, self._session_factory
        )

    async def run_claim_loop(self, engine: Any) -> bool:  # noqa: ARG002
        """Drain player_list jobs for one browser session.

        Returns True when queue is empty (stop), False on BrowserException (restart).

        Note: ``engine`` is intentionally unused here. The scraper is injected via
        ``on_browser_ready`` (temporal coupling by design) so that the same scraper
        instance can be reused across jobs within a single browser session without
        passing the engine through every call site.
        """
        from pydoll.exceptions import BrowserException as _BrowserException

        while True:
            async with get_session(self._session_factory) as session:
                job = await PlayerListQueueRepository(session).claim_next()
                await session.commit()

            if job is None:
                return True

            country_match = _COUNTRY_CODE_RE.search(job.url)
            country_code = (
                country_match.group(1).upper() if country_match else job.url
            )
            country_display = (
                self._url_to_name.get(job.url)
                or self._code_to_name.get(country_code)
                or country_code
            ).title()

            max_attempts = 3
            browser_restart = False
            for attempt in range(1, max_attempts + 1):
                try:
                    async with self._fetch_gate:
                        if self._scraper is None:
                            raise RuntimeError(
                                "scraper not initialised"
                                " — on_browser_ready must run first"
                            )
                        page, _ = await self._scraper.scrape(job.url)

                    async with get_session(self._session_factory) as session:
                        repo = PlayerListQueueRepository(session)
                        await repo.mark_done(job.id)
                        await session.commit()

                    self._processed += 1
                    self._counts[self._worker_id] = self._processed
                    total_players = len(page.players)
                    self._labels[self._worker_id] = (
                        f"{country_display}: {total_players:,} players"
                    )
                    break

                except Exception as exc:
                    if isinstance(exc, _BrowserException):
                        self._labels[self._worker_id] = (
                            "[bold red]ERROR[/] Browser error — Restarting"
                        )
                        try:
                            async with get_session(self._session_factory) as session:
                                repo = PlayerListQueueRepository(session)
                                await repo.mark_failed(job.id, str(exc))
                                await session.commit()
                        except Exception:
                            pass
                        browser_restart = True
                        break

                    if attempt < max_attempts:
                        self._labels[self._worker_id] = (
                            f"[bold yellow]WARNING[/]"
                            f" Retrying ({attempt}/{max_attempts}) — {country_display}"
                        )
                        await asyncio.sleep(2)
                    else:
                        try:
                            async with get_session(self._session_factory) as session:
                                repo = PlayerListQueueRepository(session)
                                await repo.mark_failed(job.id, str(exc))
                                await session.commit()
                        except Exception:
                            pass
                        self._labels[self._worker_id] = (
                            f"[bold red]FAILED[/] {country_display}"
                        )

            if browser_restart:
                return False


def _players_url(country_url: str) -> str:
    """Derive player-list URL from country_url stored in DB.

    /en/country/AFG/Afghanistan-Football
    → https://fbref.com/en/country/players/AFG/Afghanistan-Football
    """
    path = country_url.replace("/en/country/", "/en/country/players/", 1)
    return f"{_FBREF_BASE}{path}"


async def _load_all_countries(
    session_factory: async_sessionmaker[AsyncSession],
) -> list[tuple[str, str, str]]:
    """Return (country_id, player_list_url, country_name) for every country."""
    async with get_session(session_factory) as session:
        result = await session.execute(
            sa.select(Country.country_id, Country.country_url, Country.country_name)
            .order_by(Country.country_name)
        )
        return [
            (row.country_id, _players_url(row.country_url), row.country_name)
            for row in result
        ]


async def _seed_queue(
    session_factory: async_sessionmaker[AsyncSession],
    countries: list[tuple[str, str, str]],
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
        for _, url, _ in countries
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
        stale = await PlayerListQueueRepository(session).recover_all_stale()
        await session.commit()
    if stale:
        logger.debug("Resumed: %d interrupted jobs restored to queue", stale)

    async with get_session(session_factory) as session:
        result = await session.execute(
            sa.text(
                "SELECT count(*) FROM sch_infra.scrape_queue"
                " WHERE job_type='player_list' AND status='DONE'"
            )
        )
        initial_db_count = int(result.scalar() or 0)

    url_to_name: dict[str, str] = {url: name for _, url, name in countries}
    code_to_name: dict[str, str] = {}
    for _, url, name in countries:
        m = _COUNTRY_CODE_RE.search(url)
        if m:
            code_to_name[m.group(1).upper()] = name

    fetch_gate = asyncio.Semaphore(1)
    logger.info("Launching %d worker(s)…", workers)

    worker_labels: dict[int, str] = {}
    worker_counts: dict[int, int] = {}
    stop_event = asyncio.Event()

    with Live(
        build_worker_table(
            worker_labels, worker_counts, workers, initial_db_count, total
        ),
        console=_console,
        refresh_per_second=2,
        vertical_overflow="crop",
    ) as live:
        display_task = asyncio.create_task(
            run_display_loop(
                workers, worker_labels, worker_counts,
                initial_db_count, total, stop_event, live,
            )
        )
        results = await asyncio.gather(
            *[
                PlayerListWorker(
                    worker_id=i + 1,
                    session_factory=session_factory,
                    fetch_gate=fetch_gate,
                    profile_base=settings.scraping.chrome_profile_dir,
                    worker_labels=worker_labels,
                    worker_counts=worker_counts,
                    settings=settings,
                    url_to_name=url_to_name,
                    code_to_name=code_to_name,
                ).run()
                for i in range(workers)
            ],
            return_exceptions=True,
        )
        stop_event.set()
        await display_task
        done_text = Text("  ")
        done_text.append("✓", style="cyan")
        done_text.append("  All players scraped.")
        live.update(done_text)

    grand_total = sum(r for r in results if isinstance(r, int))
    logger.debug("Done. %d jobs processed across %d worker(s).", grand_total, workers)


async def main_countries(codes: list[str], workers: int = 1) -> None:
    if not codes:
        logger.warning("main_countries called with empty codes list — nothing to do")
        return

    settings = Settings()  # type: ignore[call-arg]

    upper_codes = [c.upper() for c in codes]
    session_factory_tmp = create_session_factory(settings.db)
    async with get_session(session_factory_tmp) as session:
        result = await session.execute(
            sa.select(
                Country.country_id, Country.country_url, Country.country_name
            ).where(
                Country.country_id.in_(upper_codes)
            )
        )
        countries = [
            (row.country_id, _players_url(row.country_url), row.country_name)
            for row in result
        ]
    total = len(countries)
    workers = 1

    settings.db.pool_size = max(workers * 2, settings.db.pool_size)
    session_factory = create_session_factory(settings.db)

    await _seed_queue(session_factory, countries)

    async with get_session(session_factory) as session:
        stale = await PlayerListQueueRepository(session).recover_all_stale()
        await session.commit()
    if stale:
        logger.debug("Resumed: %d interrupted jobs restored to queue", stale)

    async with get_session(session_factory) as session:
        result = await session.execute(
            sa.text(
                "SELECT count(*) FROM sch_infra.scrape_queue"
                " WHERE job_type='player_list' AND status='DONE'"
            )
        )
        initial_db_count = int(result.scalar() or 0)

    url_to_name: dict[str, str] = {url: name for _, url, name in countries}
    code_to_name: dict[str, str] = {}
    for _, url, name in countries:
        m = _COUNTRY_CODE_RE.search(url)
        if m:
            code_to_name[m.group(1).upper()] = name

    fetch_gate = asyncio.Semaphore(1)

    worker_labels: dict[int, str] = {}
    worker_counts: dict[int, int] = {}
    stop_event = asyncio.Event()

    with Live(
        build_worker_table(
            worker_labels, worker_counts, workers, initial_db_count, total
        ),
        console=_console,
        refresh_per_second=2,
        vertical_overflow="crop",
    ) as live:
        display_task = asyncio.create_task(
            run_display_loop(
                workers, worker_labels, worker_counts,
                initial_db_count, total, stop_event, live,
            )
        )
        results = await asyncio.gather(
            *[
                PlayerListWorker(
                    worker_id=i + 1,
                    session_factory=session_factory,
                    fetch_gate=fetch_gate,
                    profile_base=settings.scraping.chrome_profile_dir,
                    worker_labels=worker_labels,
                    worker_counts=worker_counts,
                    settings=settings,
                    url_to_name=url_to_name,
                    code_to_name=code_to_name,
                ).run()
                for i in range(workers)
            ],
            return_exceptions=True,
        )
        stop_event.set()
        await display_task
        done_text = Text("  ")
        done_text.append("✓", style="cyan")
        done_text.append("  All players scraped.")
        live.update(done_text)

    grand_total = sum(r for r in results if isinstance(r, int))
    logger.debug("Done. %d jobs processed across %d worker(s).", grand_total, workers)


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
