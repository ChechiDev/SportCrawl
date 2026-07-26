"""Country teams scraper — fetches and persists team data for each country from FBRef.

Iterates over all rows in tbl_country_squads that have a clubs_url, then scrapes
the teams/clubs listing page for each country and upserts results into tbl_teams.

Usage:
    uv run python scripts/scrape_country_teams.py
    uv run python scripts/scrape_country_teams.py --workers 3
    uv run python scripts/scrape_country_teams.py --country ARG,BRA
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

import sqlalchemy as sa
from pydoll.exceptions import BrowserException as _BrowserException
from rich.console import Console
from rich.live import Live
from rich.markup import escape as _escape
from rich.text import Text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config.settings import Settings
from core.application.base_worker import BaseWorker, CooldownRequired
from infrastructure.browser.pydoll_engine import PydollEngine
from infrastructure.display.worker_display import build_worker_table, run_display_loop
from infrastructure.persistence.models.scrape_queue import ScrapeQueue, ScrapeStatus
from infrastructure.persistence.models.shared.country_squads import CountrySquads
from infrastructure.persistence.repositories.team_list_queue import (
    TeamListQueueRepository,
)
from infrastructure.persistence.repositories.teams import TeamsRepository
from infrastructure.persistence.session import create_session_factory, get_session
from infrastructure.scraping.country_teams import CountryTeamsScraper

_console = Console()

_root_logger = logging.getLogger()
_root_logger.handlers.clear()
_root_logger.setLevel(logging.CRITICAL)

for _noisy in (
    "pydoll",
    "websockets",
    "asyncio",
    "ports",
    "ports.scraper",
    "infrastructure",
):
    logging.getLogger(_noisy).setLevel(logging.CRITICAL)
logger = logging.getLogger(__name__)


async def _seed_queue(
    session_factory: async_sessionmaker[AsyncSession],
    rows: list[tuple[str, str]],
) -> int:
    """Bulk-insert one scrape_queue row per (fk_country, clubs_url) tuple.

    ON CONFLICT DO NOTHING keeps the operation idempotent across restarts.
    Filter-agnostic: seeds exactly the rows it receives (caller applies any
    country filter before passing rows here).

    Args:
        session_factory: Async session factory.
        rows: List of (fk_country, clubs_url) tuples to seed.

    Returns:
        Number of newly inserted rows (0 when all URLs already queued or
        input is empty).
    """
    if not rows:
        return 0

    insert_rows = [
        {
            "url": clubs_url,
            "domain": "fbref.com",
            "status": ScrapeStatus.PENDING,
            "job_type": "team_list",
        }
        for _fk_country, clubs_url in rows
    ]

    _PG_MAX_PARAMS = 65_535
    _SEED_CHUNK_SIZE = _PG_MAX_PARAMS // 8  # ~8191; 8 bind params per ScrapeQueue row
    inserted = 0
    for i in range(0, len(insert_rows), _SEED_CHUNK_SIZE):
        chunk = insert_rows[i : i + _SEED_CHUNK_SIZE]
        stmt = pg_insert(ScrapeQueue).values(chunk)
        stmt = stmt.on_conflict_do_nothing(index_elements=["url", "job_type"])
        async with get_session(session_factory) as session:
            result = await session.execute(stmt)
            inserted += getattr(result, "rowcount", None) or 0
            await session.commit()

    return inserted


class CountryTeamsWorker(BaseWorker[ScrapeQueue]):
    """Worker that claims team_list jobs from scrape_queue and scrapes each country."""

    def __init__(
        self,
        worker_id: int,
        session_factory: async_sessionmaker[AsyncSession],
        fetch_gate: asyncio.Semaphore,
        profile_base: str,
        worker_labels: dict[int, str],
        worker_counts: dict[int, int],
        settings: Settings,
        url_to_country: dict[str, str] | None = None,
        country_filter: set[str] | None = None,
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
        self._url_to_country: dict[str, str] = url_to_country or {}
        self._country_filter = country_filter
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
        delay = self._worker_id - 1
        if delay:
            await asyncio.sleep(delay)

    async def run_claim_loop(self, engine: Any) -> int:
        from infrastructure.persistence.models.shared.gender import Gender as _Gender

        # Pre-load gender map once per browser session to avoid repeated SELECTs.
        gender_map: dict[str, int] | None = None
        async with get_session(self._session_factory) as _session:
            _result = await _session.execute(sa.select(_Gender.id, _Gender.gender))
            gender_map = {row.gender: row.id for row in _result}

        while True:
            # Claim next job from the persistent queue.
            async with get_session(self._session_factory) as session:
                job = await TeamListQueueRepository(session).claim_next_filtered(
                    country_filter=self._country_filter
                )
                await session.commit()

            if job is None:
                return self._processed

            # Resolve fk_country from pre-loaded map. Fresh session guard: the
            # claim session is already committed and closed at this point.
            fk_country = self._url_to_country.get(job.url)
            if fk_country is None:
                async with get_session(self._session_factory) as session:
                    await TeamListQueueRepository(session).mark_failed(
                        job.id, f"fk_country not found for url: {job.url}"
                    )
                    await session.commit()
                continue

            clubs_url = job.url
            max_attempts = 3
            browser_restart = False
            success = False

            for attempt in range(1, max_attempts + 1):
                try:
                    async with self._fetch_gate:
                        scraper = CountryTeamsScraper(
                            engine=engine,
                            settings=self._settings.scraping,
                            fk_country=fk_country,
                        )
                        page = await scraper.scrape(clubs_url)

                    async with get_session(self._session_factory) as session:
                        repo = TeamsRepository(session, gender_map=gender_map)
                        await repo.upsert(page.teams)
                        await TeamListQueueRepository(session).mark_done(job.id)
                        await session.commit()

                    self._processed += 1
                    self._counts[self._worker_id] = self._processed
                    country_display = self._country_names.get(fk_country, fk_country)
                    self._labels[self._worker_id] = (
                        f"{_escape(country_display)}: {len(page.teams)} Teams"
                    )
                    success = True
                    break

                except _BrowserException as exc:
                    self._labels[self._worker_id] = (
                        "[bold red]ERROR[/] Browser error — Restarting"
                    )
                    try:
                        async with get_session(self._session_factory) as session:
                            await TeamListQueueRepository(session).mark_failed(
                                job.id, str(exc)
                            )
                            await session.commit()
                    except Exception as mark_err:
                        logger.error(
                            "[worker-%d] mark_failed error: %s",
                            self._worker_id,
                            mark_err,
                        )
                    browser_restart = True
                    break

                except Exception as exc:
                    if attempt < max_attempts:
                        self._labels[self._worker_id] = (
                            f"[bold yellow]WARNING[/]"
                            f" Retrying ({attempt}/{max_attempts}) — {fk_country}"
                        )
                        await asyncio.sleep(random.uniform(5.0, 15.0))
                    else:
                        self._labels[self._worker_id] = (
                            f"[bold red]FAILED[/] {fk_country}"
                        )
                        logger.error(
                            "Failed to scrape %s after %d attempts: %s",
                            fk_country,
                            max_attempts,
                            exc,
                        )
                        async with get_session(self._session_factory) as session:
                            await TeamListQueueRepository(session).mark_failed(
                                job.id,
                                f"Exhausted {max_attempts} attempts: {exc}",
                            )
                            await session.commit()

            if browser_restart:
                return -1

            if not success:
                self._labels[self._worker_id] = (
                    f"[bold red]FAILED[/] {fk_country} — max retries reached"
                )
                raise CooldownRequired


async def main(workers: int = 1, country_filter: set[str] | None = None) -> None:
    settings = Settings()  # type: ignore[call-arg]
    settings.db.pool_size = max(workers * 2, settings.db.pool_size)
    session_factory = create_session_factory(settings.db)

    async with get_session(session_factory) as session:
        result = await session.execute(
            sa.select(CountrySquads.fk_country, CountrySquads.clubs_url)
            .where(CountrySquads.clubs_url.isnot(None))
            .order_by(CountrySquads.fk_country)
        )
        all_rows: list[tuple[str, str]] = [
            (row.fk_country, row.clubs_url) for row in result
        ]

    if country_filter is not None:
        rows = [(fk, url) for fk, url in all_rows if fk in country_filter]
    else:
        rows = all_rows

    url_to_country = {clubs_url: fk_country for fk_country, clubs_url in rows}

    await _seed_queue(session_factory, rows)

    async with get_session(session_factory) as session:
        await TeamListQueueRepository(session).recover_all_stale()
        await TeamListQueueRepository(session).recover_failed()
        await session.commit()

    async with get_session(session_factory) as session:
        result = await session.execute(
            sa.text(
                "SELECT count(*) FROM sch_infra.scrape_queue"
                " WHERE job_type='team_list' AND status='PENDING'"
            )
        )
        total = int(result.scalar() or 0)

    logger.info("team_list PENDING jobs: %d", total)

    fetch_gate = asyncio.Semaphore(1)

    async with get_session(session_factory) as session:
        names_result = await session.execute(
            sa.select(
                sa.text("country_id"),
                sa.text("country_name"),
            ).select_from(sa.text("sch_shared.tbl_countries"))
        )
        country_names = {r[0]: r[1] for r in names_result}

    worker_labels: dict[int, str] = {}
    worker_counts: dict[int, int] = {}
    stop_event = asyncio.Event()

    worker_count = min(total, workers) if total else 0

    with Live(
        build_worker_table(worker_labels, worker_counts, worker_count, 0, total),
        console=_console,
        refresh_per_second=2,
        vertical_overflow="crop",
    ) as live:
        display_task = asyncio.create_task(
            run_display_loop(
                worker_count,
                worker_labels,
                worker_counts,
                0,
                total,
                stop_event,
                live,
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
                    url_to_country=url_to_country,
                    country_filter=country_filter,
                    country_names=country_names,
                ).run()
                for i in range(worker_count)
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
    logger.debug(
        "Done. %d countries processed across %d worker(s).", grand_total, workers
    )


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
    parser.add_argument(
        "--country",
        metavar="CODES",
        type=str,
        default=None,
        help="Comma-separated ISO country codes to scrape (e.g. ARG,BRA). "
        "Omit to scrape all queued countries.",
    )
    args = parser.parse_args()
    country_filter: set[str] | None = None
    if args.country:
        country_filter = {c.strip().upper() for c in args.country.split(",")}
    asyncio.run(main(workers=args.workers, country_filter=country_filter))


if __name__ == "__main__":
    run()
