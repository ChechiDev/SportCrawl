"""Country teams scraper — fetches and persists team data for each country from FBRef.

Iterates over all rows in tbl_country_squads that have a clubs_url, then scrapes
the teams/clubs listing page for each country and upserts results into tbl_teams.

Usage:
    uv run python scripts/scrape_country_teams.py
    uv run python scripts/scrape_country_teams.py --workers 3
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import sqlalchemy as sa
from rich.console import Console
from rich.live import Live
from rich.text import Text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config.settings import Settings
from core.application.base_worker import BaseWorker
from infrastructure.browser.pydoll_engine import PydollEngine
from infrastructure.display.worker_display import build_worker_table, run_display_loop
from infrastructure.persistence.models.shared.country_squads import CountrySquads
from infrastructure.persistence.session import create_session_factory, get_session
from infrastructure.scraping.country_teams import CountryTeamsScraper

_console = Console()

_root_logger = logging.getLogger()
_root_logger.handlers.clear()
_root_logger.setLevel(logging.CRITICAL)

for _noisy in (
    "pydoll", "websockets", "asyncio", "ports", "ports.scraper", "infrastructure"
):
    logging.getLogger(_noisy).setLevel(logging.CRITICAL)
logger = logging.getLogger(__name__)


class CountryTeamsWorker(BaseWorker[tuple[str, str]]):
    """Worker that drains an in-memory queue of (fk_country, clubs_url) tuples."""

    def __init__(
        self,
        worker_id: int,
        session_factory: async_sessionmaker[AsyncSession],
        fetch_gate: asyncio.Semaphore,
        profile_base: str,
        worker_labels: dict[int, str],
        worker_counts: dict[int, int],
        settings: Settings,
        queue: asyncio.Queue[tuple[str, str]],
        country_names: dict[str, str] | None = None,
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
        self._queue = queue
        self._country_names = country_names or {}

    @property
    def profile_dir(self) -> str:
        return f"{self._profile_base}-country-teams-{self._worker_id}"

    @property
    def engine_name(self) -> str:
        return f"CountryTeams-{self._worker_id}"

    def _build_engine(self) -> PydollEngine:
        return PydollEngine(profile_dir=self.profile_dir, name=self.engine_name)

    async def startup_delay(self) -> None:
        delay = (self._worker_id - 1) * 1
        if delay:
            await asyncio.sleep(delay)

    async def run_claim_loop(self, engine: Any) -> bool:
        from pydoll.exceptions import BrowserException as _BrowserException

        while True:
            try:
                fk_country, clubs_url = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                return True

            max_attempts = 3
            browser_restart = False

            for attempt in range(1, max_attempts + 1):
                try:
                    async with self._fetch_gate:
                        scraper = CountryTeamsScraper(
                            engine=engine,
                            settings=self._settings.scraping,
                            session_factory=self._session_factory,
                            fk_country=fk_country,
                        )
                        page = await scraper.scrape(clubs_url)

                    async with get_session(self._session_factory) as session:
                        await scraper.persist(page, session)
                        await session.commit()

                    self._processed += 1
                    self._counts[self._worker_id] = self._processed
                    country_display = self._country_names.get(fk_country, fk_country)
                    self._labels[self._worker_id] = (
                        f"{country_display}: {len(page.teams)} teams"
                    )
                    break

                except Exception as exc:
                    if isinstance(exc, _BrowserException):
                        self._labels[self._worker_id] = (
                            "[bold red]ERROR[/] Browser error — Restarting"
                        )
                        browser_restart = True
                        # Put the item back so another worker can claim it
                        await self._queue.put((fk_country, clubs_url))
                        break

                    if attempt < max_attempts:
                        self._labels[self._worker_id] = (
                            f"[bold yellow]WARNING[/]"
                            f" Retrying ({attempt}/{max_attempts}) — {fk_country}"
                        )
                        await asyncio.sleep(2)
                    else:
                        self._labels[self._worker_id] = (
                            f"[bold red]FAILED[/] {fk_country}"
                        )

            if browser_restart:
                return False


async def main(workers: int = 1) -> None:
    settings = Settings()  # type: ignore[call-arg]
    settings.db.pool_size = max(workers * 2, settings.db.pool_size)
    session_factory = create_session_factory(settings.db)

    async with get_session(session_factory) as session:
        result = await session.execute(
            sa.select(CountrySquads.fk_country, CountrySquads.clubs_url).where(
                CountrySquads.clubs_url.isnot(None)
            ).order_by(CountrySquads.fk_country)
        )
        rows = result.fetchall()

    total = len(rows)
    logger.info("Loaded %d countries with clubs_url", total)

    queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue()
    for fk_country, clubs_url in rows:
        await queue.put((fk_country, clubs_url))

    fetch_gate = asyncio.Semaphore(1)

    worker_labels: dict[int, str] = {}
    worker_counts: dict[int, int] = {}
    stop_event = asyncio.Event()

    with Live(
        build_worker_table(worker_labels, worker_counts, workers, 0, total),
        console=_console,
        refresh_per_second=2,
        vertical_overflow="crop",
    ) as live:
        display_task = asyncio.create_task(
            run_display_loop(
                workers, worker_labels, worker_counts,
                0, total, stop_event, live,
            )
        )
        results = await asyncio.gather(
            *[
                CountryTeamsWorker(
                    worker_id=i + 1,
                    session_factory=session_factory,
                    fetch_gate=fetch_gate,
                    profile_base=settings.scraping.chrome_profile_dir,
                    worker_labels=worker_labels,
                    worker_counts=worker_counts,
                    settings=settings,
                    queue=queue,
                ).run()
                for i in range(workers)
            ],
            return_exceptions=True,
        )
        stop_event.set()
        await display_task
        done_text = Text("  ")
        done_text.append("✓", style="cyan")
        done_text.append("  All country teams scraped.")
        live.update(done_text)

    grand_total = sum(r for r in results if isinstance(r, int))
    logger.debug("Done. %d countries processed across %d worker(s).", grand_total, workers)


def run() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Scrape FBRef country team listings.")
    parser.add_argument(
        "--workers",
        metavar="N",
        type=int,
        default=1,
        help="Number of parallel workers (default: 1).",
    )
    args = parser.parse_args()
    asyncio.run(main(workers=args.workers))


if __name__ == "__main__":
    run()
