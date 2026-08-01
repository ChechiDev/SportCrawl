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
from infrastructure.persistence.models.scrape_queue import ScrapeQueue
from infrastructure.persistence.repositories.backend_urls import BackendUrlRepository
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
    """Seed scrape_queue with (country_code, url) pairs for team_list jobs.

    Returns the number of inserted rows. Returns 0 immediately for empty input
    without touching the database.
    """
    if not rows:
        return 0
    values = [
        {
            "url": url,
            "domain": "fbref.com",
            "status": "PENDING",
            "job_type": "team_list",
            "fk_country": country_code,
        }
        for country_code, url in rows
    ]
    stmt = pg_insert(ScrapeQueue).values(values).on_conflict_do_nothing()
    async with get_session(session_factory) as session:
        from sqlalchemy.engine import CursorResult

        cursor: CursorResult[Any] = (
            await session.execute(stmt)  # type: ignore[assignment]
        )
        await session.commit()
        return cursor.rowcount or 0


async def _notify_all_due(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Seed scrape_queue with team_list jobs from tbl_country_squad_urls.

    Directly inserts due rows (url_type='clubs') into scrape_queue so workers
    can start immediately without waiting for the background daemon.
    ON CONFLICT DO UPDATE keeps fk_url_registry_id in sync if a row was already
    queued by a previous run.
    """
    async with get_session(session_factory) as session:
        result = await session.execute(
            sa.text("SELECT count(*) FROM sch_fbref_backend.tbl_country_squad_urls")
        )
        if not int(result.scalar() or 0):
            logger.error(
                "tbl_country_squad_urls is empty — nothing to notify; "
                "run the country squads scraper first"
            )
            return
        await session.execute(
            sa.text(
                "INSERT INTO sch_fbref_infra.scrape_queue"
                "  (url, domain, status, job_type, fk_url_registry_id, fk_country)"
                " SELECT url, 'fbref.com', 'PENDING', 'team_list', id, fk_country"
                " FROM sch_fbref_backend.tbl_country_squad_urls"
                " WHERE url_type = 'clubs'"
                "   AND status = 'PENDING'"
                "   AND next_scrape_at <= now()"
                " ON CONFLICT ON CONSTRAINT uq_scrape_queue_url_job_type DO UPDATE"
                "   SET fk_url_registry_id = EXCLUDED.fk_url_registry_id,"
                "       fk_country         = EXCLUDED.fk_country"
                " WHERE scrape_queue.fk_url_registry_id IS NULL"
            )
        )
        await session.commit()


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

            # fk_country is stored directly on the queue row (set at seed time).
            fk_country = job.fk_country
            if fk_country is None:
                _no_country_msg = (
                    f"fk_country not set on queue row id={job.id} url={job.url}"
                )
                async with get_session(self._session_factory) as session:
                    await TeamListQueueRepository(session).mark_failed(
                        job.id, _no_country_msg
                    )
                    await session.commit()
                if job.fk_url_registry_id is not None:
                    try:
                        async with get_session(self._session_factory) as _s:
                            await BackendUrlRepository(_s).mark_failed(
                                "tbl_team_urls",
                                job.fk_url_registry_id,
                                error=_no_country_msg,
                            )
                            await _s.commit()
                    except Exception as _backend_err:
                        logger.warning(
                            "[worker-%d] backend mark_failed failed (job %d): %s",
                            self._worker_id,
                            job.id,
                            _backend_err,
                        )
                continue

            clubs_url = job.url
            max_attempts = 3
            browser_restart = False
            success = False

            for attempt in range(1, max_attempts + 1):
                try:
                    # TODO(fix5): narrow fetch_gate to navigate() only.
                    # CountryTeamsScraper.scrape() calls BaseScraper.fetch_and_parse()
                    # which uses engine.fetch() — a monolithic navigate+wait call.
                    # Splitting requires exposing navigate/wait_for_challenge on
                    # BaseScraper or bypassing it in the worker. Deferred.
                    async with self._fetch_gate:
                        scraper = CountryTeamsScraper(
                            engine=engine,
                            settings=self._settings.scraping,
                            fk_country=fk_country,
                        )
                        page = await scraper.scrape(clubs_url)

                    # mark_scraped first (idempotent): if it fails, the queue job
                    # stays IN_PROGRESS and recover_stale will retry the whole item.
                    if job.fk_url_registry_id is not None:
                        try:
                            async with get_session(self._session_factory) as _s:
                                await BackendUrlRepository(_s).mark_scraped(
                                    "tbl_team_urls", job.fk_url_registry_id
                                )
                                await _s.commit()
                        except Exception as _backend_err:
                            logger.warning(
                                "[worker-%d] backend mark_scraped failed (job %d): %s",
                                self._worker_id,
                                job.id,
                                _backend_err,
                            )

                    async with get_session(self._session_factory) as session:
                        repo = TeamsRepository(session, gender_map=gender_map)
                        await repo.upsert(page.teams)
                        await TeamListQueueRepository(session).mark_done(job.id)
                        await session.commit()

                    self._processed += 1
                    self._counts[self._worker_id] = self._processed
                    country_display = self._country_names.get(
                        fk_country, fk_country or ""
                    )
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
                    if job.fk_url_registry_id is not None:
                        try:
                            async with get_session(self._session_factory) as _s:
                                await BackendUrlRepository(_s).mark_failed(
                                    "tbl_team_urls",
                                    job.fk_url_registry_id,
                                    error=str(exc),
                                )
                                await _s.commit()
                        except Exception as _backend_err:
                            logger.warning(
                                "[worker-%d] backend mark_failed failed (job %d): %s",
                                self._worker_id,
                                job.id,
                                _backend_err,
                            )
                    browser_restart = True
                    break

                except Exception as exc:
                    if attempt < max_attempts:
                        self._labels[self._worker_id] = (
                            f"[bold yellow]WARNING[/bold yellow]"
                            f" - Retrying ({attempt}/{max_attempts}) - {fk_country}"
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
                        _fail_msg = f"Exhausted {max_attempts} attempts: {exc}"
                        async with get_session(self._session_factory) as session:
                            await TeamListQueueRepository(session).mark_failed(
                                job.id,
                                _fail_msg,
                            )
                            await session.commit()
                        if job.fk_url_registry_id is not None:
                            try:
                                async with get_session(self._session_factory) as _s:
                                    await BackendUrlRepository(_s).mark_failed(
                                        "tbl_team_urls",
                                        job.fk_url_registry_id,
                                        error=_fail_msg,
                                    )
                                    await _s.commit()
                            except Exception as _backend_err:
                                logger.warning(
                                    "[worker-%d] backend mark_failed"
                                    " failed (job %d): %s",
                                    self._worker_id,
                                    job.id,
                                    _backend_err,
                                )

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

    await _notify_all_due(session_factory)

    async with get_session(session_factory) as session:
        await TeamListQueueRepository(session).recover_all_stale()
        await TeamListQueueRepository(session).recover_failed()
        await session.commit()

    async with get_session(session_factory) as session:
        result = await session.execute(
            sa.text(
                "SELECT count(*) FROM sch_fbref_infra.scrape_queue"
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
            ).select_from(sa.text("sch_fbref_shared.tbl_countries"))
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
