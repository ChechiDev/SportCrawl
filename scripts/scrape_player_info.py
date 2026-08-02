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
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from infrastructure.persistence.models.scrape_queue import ScrapeQueue  # noqa: F401

import sqlalchemy as sa
from pydoll.exceptions import BrowserException
from rich.console import Console
from rich.live import Live
from rich.markup import escape
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config.settings import Settings
from core.application.base_worker import BaseWorker, CooldownRequired
from core.application.scrape_job_processor import ScrapeJobProcessor
from core.exceptions.scraper import PageLoadError, RateLimitError
from infrastructure.browser import PydollEngine, XvfbDisplay
from infrastructure.browser.dispatch import (
    BoundedCandidateBuffer,
    CandidateProducer,
)
from infrastructure.display.worker_display import build_worker_table, run_display_loop
from infrastructure.persistence.repositories.backend_urls import BackendUrlRepository
from infrastructure.persistence.repositories.player_info import PlayerInfoRepository
from infrastructure.persistence.repositories.player_info_queue import (
    PlayerInfoConsistencyError,
    PlayerInfoQueueRepository,
    record_job_failure,
)
from infrastructure.persistence.repositories.player_misc_stats import (
    PlayerMiscStatsRepository,
)
from infrastructure.persistence.repositories.player_playing_time_stats import (
    PlayerPlayingTimeStatsRepository,
)
from infrastructure.persistence.repositories.player_shooting_stats import (
    PlayerShootingStatsRepository,
)
from infrastructure.persistence.repositories.player_std_stats import (
    PlayerStdStatsRepository,
)
from infrastructure.persistence.session import create_session_factory, get_session
from infrastructure.scraping.player_info import PlayerInfoScraper
from infrastructure.scraping.player_misc_stats import parse_player_misc_stats
from infrastructure.scraping.player_playing_time_stats import (
    parse_player_playing_time_stats,
)
from infrastructure.scraping.player_shooting_stats import parse_player_shooting_stats
from infrastructure.scraping.player_std_stats import parse_player_std_stats

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
# Failure-recording helper
# ---------------------------------------------------------------------------


async def _record_failure_with_retry(
    job_id: int,
    error: str,
    max_queue_retries: int,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    _max_attempts: int = 3,
) -> None:
    """Attempt record_job_failure with bounded exponential backoff.

    Uses lock_timeout (set inside record_job_failure) and retries on transient
    database errors. If all attempts are exhausted, raises RuntimeError to stop
    the current worker — the next startup will run recover_all_stale().

    Does NOT silently swallow durable failures.
    """
    last_exc: BaseException | None = None
    for attempt in range(1, _max_attempts + 1):
        try:
            await record_job_failure(
                job_id, error, max_queue_retries, session_factory
            )
            return
        except PlayerInfoConsistencyError:
            raise
        except Exception as exc:
            last_exc = exc
            delay = (2.0 ** (attempt - 1)) + random.uniform(0.0, 1.0)
            logger.error(
                "record_job_failure attempt %d/%d for job %d failed: %s;"
                " retrying in %.1fs",
                attempt,
                _max_attempts,
                job_id,
                type(exc).__name__,
                delay,
            )
            if attempt < _max_attempts:
                await asyncio.sleep(delay)
    raise RuntimeError(
        f"FATAL: cannot record failure for job {job_id}"
        f" after {_max_attempts} attempts: {last_exc}"
    ) from last_exc


# ---------------------------------------------------------------------------
# Position resolver
# ---------------------------------------------------------------------------


async def _load_country_ids(
    session_factory: async_sessionmaker[AsyncSession],
) -> frozenset[str]:
    """Load all valid country_id values from tbl_countries into a frozenset."""
    async with get_session(session_factory) as session:
        result = await session.execute(
            sa.text("SELECT country_id FROM sch_fbref_shared.tbl_countries")
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
                "SELECT country_name, country_id FROM sch_fbref_shared.tbl_countries"
            )
        )
        cache = {row[0]: row[1] for row in result.fetchall()}

    # FBRef uses "United Kingdom" in player birth fields but stores England/Scotland
    # separately — map it to GBR (Great Britain) which is the sovereign country.
    gb_id = cache.get("Great Britain") or cache.get("GBR")
    if gb_id:
        cache.setdefault("United Kingdom", gb_id)

    # FBRef country page names differ from player page names for some countries.
    _aliases: list[tuple[str, str]] = [
        ("IR Iran", "Iran"),
        ("Korea Republic", "South Korea"),
        ("Korea DPR", "North Korea"),
        ("China PR", "China"),
    ]
    for db_name, fbref_name in _aliases:
        country_id = cache.get(db_name)
        if country_id:
            cache.setdefault(fbref_name, country_id)

    return cache


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
        max_queue_retries: int = 5,
        display: XvfbDisplay | None = None,
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
        self._max_queue_retries: int = max_queue_retries
        self._display: XvfbDisplay | None = display

    async def on_browser_ready(self, engine: Any) -> None:
        from ports.browser import WarmableEngine
        if not isinstance(engine, WarmableEngine):
            return
        await engine.warmup(self._fbref_base_url)

    @property
    def profile_dir(self) -> str:
        return f"{self._profile_base}-{self._worker_id}"

    @property
    def engine_name(self) -> str:
        return f"Crawl-{self._worker_id}"

    def _build_engine(self) -> PydollEngine:
        return PydollEngine(
            profile_dir=self.profile_dir,
            name=self.engine_name,
            display=self._display,
        )

    async def startup_delay(self) -> None:
        delay = self._worker_id * random.uniform(1.5, 3.0)
        self._labels[self._worker_id] = f"Waiting {delay:.1f}s before start..."
        await asyncio.sleep(delay)

    async def run_claim_loop(self, engine: Any) -> int:
        """Process player_info jobs for one browser session.

        Returns self._processed when queue is empty and step2 is done (stop).
        Returns -1 on BrowserException (restart browser).
        """
        self._labels[self._worker_id] = "Starting crawl..."

        while True:
            async with get_session(self._session_factory) as session:
                queue_repo = PlayerInfoQueueRepository(
                    session, max_queue_retries=self._max_queue_retries
                )
                job = await queue_repo.claim_next()
                await session.commit()

            if job is None:
                if self._step2_done is None or self._step2_done.is_set():
                    return self._processed
                self._labels[self._worker_id] = "[dim]Waiting for step 2...[/]"
                await asyncio.sleep(10)
                continue

            attempt = 0
            success = False
            browser_restart = False
            _scrape_failed = False

            while attempt < 3 and not success:
                try:
                    async with self._fetch_gate:
                        await engine.navigate(job.url)
                        await asyncio.sleep(random.uniform(2.0, 6.0))
                    # Challenge polling and cooldown run outside gate so other
                    # workers are not blocked during Cloudflare resolution.
                    html = await engine.wait_for_challenge(job.url)
                    await asyncio.sleep(random.uniform(3, 10))
                    if not html:
                        raise PageLoadError(
                            "empty HTML response",
                            url=job.url,
                        )

                    scraper = PlayerInfoScraper(
                        player_id=_player_id_from_url(job.url),
                    )

                    async with get_session(self._session_factory) as session:
                        info_repo = PlayerInfoRepository(session)
                        q_repo = PlayerInfoQueueRepository(
                            session, max_queue_retries=self._max_queue_retries
                        )
                        processor = ScrapeJobProcessor(
                            scraper=scraper,
                            queue_repo=q_repo,
                            player_info_repo=info_repo,
                            country_name_cache=self._country_name_cache,
                            position_cache=self._position_cache,
                            valid_countries=self._valid_countries,
                        )
                        result = await processor.process(
                            job,  # type: ignore[arg-type]
                            html,
                        )

                        player_id = _player_id_from_url(job.url)

                        std_stats = parse_player_std_stats(html, player_id)
                        if std_stats:
                            std_repo = PlayerStdStatsRepository(session)
                            await std_repo.upsert_bulk(std_stats)

                        shooting_stats = parse_player_shooting_stats(html, player_id)
                        if shooting_stats:
                            shooting_repo = PlayerShootingStatsRepository(session)
                            await shooting_repo.upsert_bulk(shooting_stats)

                        playing_time_stats = parse_player_playing_time_stats(
                            html, player_id
                        )
                        if playing_time_stats:
                            playing_time_repo = PlayerPlayingTimeStatsRepository(
                                session
                            )
                            await playing_time_repo.upsert_bulk(playing_time_stats)

                        misc_stats = parse_player_misc_stats(html, player_id)
                        if misc_stats:
                            misc_repo = PlayerMiscStatsRepository(session)
                            await misc_repo.upsert_bulk(misc_stats)

                        # Atomic: mark_scraped on URL registry in the same session
                        if job.fk_url_registry_id is not None:
                            await BackendUrlRepository(session).mark_scraped(
                                "tbl_player_urls", job.fk_url_registry_id
                            )

                        await session.commit()

                    success = True
                    self._processed += 1
                    self._counts[self._worker_id] = self._processed
                    self._labels[self._worker_id] = escape(result[0] or "unknown")

                except (PageLoadError, RateLimitError, BrowserException) as exc:
                    attempt += 1
                    if isinstance(exc, BrowserException):
                        self._labels[self._worker_id] = (
                            "[bold red]ERROR[/] Browser error — Restarting"
                        )
                        await _record_failure_with_retry(
                            job.id,
                            str(exc),
                            self._max_queue_retries,
                            self._session_factory,
                        )
                        browser_restart = True
                        break
                    is_terminal_attempt = attempt >= 3
                    if is_terminal_attempt:
                        _scrape_failed = True
                        self._labels[self._worker_id] = (
                            f"[bold red]FAILED[/] Job {job.id} — {escape(str(exc))}"
                        )
                        await _record_failure_with_retry(
                            job.id,
                            str(exc),
                            self._max_queue_retries,
                            self._session_factory,
                        )
                    else:
                        self._labels[self._worker_id] = (
                            f"[bold yellow]WARNING[/bold yellow]"
                            f" - Retrying ({attempt}/3)"
                            f" - {_player_name_from_url(job.url)}"
                        )
                        await asyncio.sleep(random.uniform(5.0, 15.0))
                except Exception as exc:  # noqa: BLE001
                    logger.error(exc, exc_info=True)
                    await _record_failure_with_retry(
                        job.id,
                        str(exc),
                        self._max_queue_retries,
                        self._session_factory,
                    )
                    success = False
                    break

            if browser_restart:
                return -1

            if not success:
                if _scrape_failed:
                    self._labels[self._worker_id] = (
                        f"[bold red]FAILED[/] Job {job.id} — max retries reached"
                    )
                    raise CooldownRequired
                # DB or unexpected error: log and continue to next job
                self._labels[self._worker_id] = (
                    f"[bold yellow]SKIP[/] Job {job.id} — unexpected error"
                )

    async def run_buffered(self, buffer: BoundedCandidateBuffer) -> int:
        """Process player_info jobs using the bounded candidate dispatch buffer.

        Mirrors BaseWorker.run() engine lifecycle but consumes jobs from the
        dispatch buffer instead of calling claim_next(). Gets a CandidateRef
        from the buffer (blocks until available or shutdown), then claims the
        job from PostgreSQL at handoff — short transaction, no lock held during
        buffer wait.

        If claim fails (race with another worker/process), discards the ref and
        loops. At-least-once: a crash between claim and commit leaves the job
        IN_PROGRESS; recover_all_stale() at next startup resets it.

        Engine lifecycle mirrors BaseWorker.run(): startup delay, build engine,
        on_browser_ready hook, then the buffered claim loop. On BrowserException
        the browser restarts; on clean buffer exhaustion the method returns.
        """
        _w_log = logging.getLogger(__name__)
        await self.startup_delay()

        _MAX_RESTARTS = 5
        restart_count = 0

        while True:
            _cooldown_required = False
            try:
                async with self._build_engine() as engine:
                    try:
                        restart_count = 0
                        await self.on_browser_ready(engine)
                        loop_result = await self._run_buffered_loop(engine, buffer)
                    except CooldownRequired:
                        _cooldown_required = True
                        loop_result = -1
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        _w_log.error(exc, exc_info=True)
                        self._labels[self._worker_id] = "unexpected error — restarting"
                        await asyncio.sleep(5)
                        continue
                    if loop_result >= 0:
                        return self._processed

            except asyncio.CancelledError:
                raise
            except Exception:
                restart_count += 1
                if restart_count >= _MAX_RESTARTS:
                    self._labels[self._worker_id] = (
                        f"[bold red]ERROR[/] Browser failed"
                        f" {_MAX_RESTARTS}x — waiting 60s"
                    )
                    await asyncio.sleep(60)
                    restart_count = 0
                    continue
                self._labels[self._worker_id] = (
                    f"[bold yellow]WARNING[/] Browser start failed"
                    f" — retry {restart_count}/{_MAX_RESTARTS}"
                )
                await asyncio.sleep(10)
                continue

            if _cooldown_required:
                self._labels[self._worker_id] = (
                    f"__cooldown__{time.monotonic() + 60}"
                )
                await asyncio.sleep(60)
                await asyncio.sleep(random.uniform(0, 5))
                continue

    async def _run_buffered_loop(
        self, engine: Any, buffer: BoundedCandidateBuffer
    ) -> int:
        """Inner buffered claim loop for one browser session.

        Returns self._processed when buffer is exhausted (sentinel received).
        Returns -1 on BrowserException (triggers browser restart in run_buffered).
        """
        self._labels[self._worker_id] = "Starting buffered crawl..."

        while True:
            # Guard: if buffer is already closed and empty (e.g., this is a
            # browser restart and the sentinel was consumed in the prior session),
            # exit immediately instead of blocking on get() forever.
            if buffer.is_exhausted:
                return self._processed
            ref = await buffer.get()
            if ref is None:
                # Shutdown sentinel received — queue is exhausted.
                return self._processed

            # Claim at handoff: short DB transaction, closed immediately.
            async with get_session(self._session_factory) as session:
                queue_repo = PlayerInfoQueueRepository(
                    session, max_queue_retries=self._max_queue_retries
                )
                job = await queue_repo.claim_by_id(ref.job_id)
                await session.commit()

            buffer.task_done()

            if job is None:
                # Race: another process/worker claimed this job first. Discard.
                logger.debug(
                    "dispatch: job %d already claimed, skipping", ref.job_id
                )
                continue

            attempt = 0
            success = False
            browser_restart = False
            _scrape_failed = False

            while attempt < 3 and not success:
                try:
                    async with self._fetch_gate:
                        await engine.navigate(job.url)
                        await asyncio.sleep(random.uniform(2.0, 6.0))
                    html = await engine.wait_for_challenge(job.url)
                    await asyncio.sleep(random.uniform(3, 10))
                    if not html:
                        raise PageLoadError("empty HTML response", url=job.url)

                    scraper = PlayerInfoScraper(
                        player_id=_player_id_from_url(job.url),
                    )

                    async with get_session(self._session_factory) as session:
                        info_repo = PlayerInfoRepository(session)
                        q_repo = PlayerInfoQueueRepository(
                            session, max_queue_retries=self._max_queue_retries
                        )
                        processor = ScrapeJobProcessor(
                            scraper=scraper,
                            queue_repo=q_repo,
                            player_info_repo=info_repo,
                            country_name_cache=self._country_name_cache,
                            position_cache=self._position_cache,
                            valid_countries=self._valid_countries,
                        )
                        result = await processor.process(
                            job,  # type: ignore[arg-type]
                            html,
                        )

                        player_id = _player_id_from_url(job.url)

                        std_stats = parse_player_std_stats(html, player_id)
                        if std_stats:
                            std_repo = PlayerStdStatsRepository(session)
                            await std_repo.upsert_bulk(std_stats)

                        shooting_stats = parse_player_shooting_stats(html, player_id)
                        if shooting_stats:
                            shooting_repo = PlayerShootingStatsRepository(session)
                            await shooting_repo.upsert_bulk(shooting_stats)

                        playing_time_stats = parse_player_playing_time_stats(
                            html, player_id
                        )
                        if playing_time_stats:
                            playing_time_repo = PlayerPlayingTimeStatsRepository(
                                session
                            )
                            await playing_time_repo.upsert_bulk(playing_time_stats)

                        misc_stats = parse_player_misc_stats(html, player_id)
                        if misc_stats:
                            misc_repo = PlayerMiscStatsRepository(session)
                            await misc_repo.upsert_bulk(misc_stats)

                        if job.fk_url_registry_id is not None:
                            await BackendUrlRepository(session).mark_scraped(
                                "tbl_player_urls", job.fk_url_registry_id
                            )

                        await session.commit()

                    success = True
                    self._processed += 1
                    self._counts[self._worker_id] = self._processed
                    self._labels[self._worker_id] = escape(result[0] or "unknown")

                except (PageLoadError, RateLimitError, BrowserException) as exc:
                    attempt += 1
                    if isinstance(exc, BrowserException):
                        self._labels[self._worker_id] = (
                            "[bold red]ERROR[/] Browser error — Restarting"
                        )
                        await _record_failure_with_retry(
                            job.id,
                            str(exc),
                            self._max_queue_retries,
                            self._session_factory,
                        )
                        browser_restart = True
                        break
                    is_terminal_attempt = attempt >= 3
                    if is_terminal_attempt:
                        _scrape_failed = True
                        self._labels[self._worker_id] = (
                            f"[bold red]FAILED[/] Job {job.id} — {escape(str(exc))}"
                        )
                        await _record_failure_with_retry(
                            job.id,
                            str(exc),
                            self._max_queue_retries,
                            self._session_factory,
                        )
                    else:
                        self._labels[self._worker_id] = (
                            f"[bold yellow]WARNING[/bold yellow]"
                            f" - Retrying ({attempt}/3)"
                            f" - {_player_name_from_url(job.url)}"
                        )
                        await asyncio.sleep(random.uniform(5.0, 15.0))
                except Exception as exc:  # noqa: BLE001
                    logger.error(exc, exc_info=True)
                    await _record_failure_with_retry(
                        job.id,
                        str(exc),
                        self._max_queue_retries,
                        self._session_factory,
                    )
                    success = False
                    break

            if browser_restart:
                return -1

            if not success:
                if _scrape_failed:
                    self._labels[self._worker_id] = (
                        f"[bold red]FAILED[/] Job {job.id} — max retries reached"
                    )
                    raise CooldownRequired
                self._labels[self._worker_id] = (
                    f"[bold yellow]SKIP[/] Job {job.id} — unexpected error"
                )


def _player_name_from_url(url: str) -> str:
    parts = url.rstrip("/").split("/")
    try:
        idx = parts.index("players")
        slug = parts[idx + 2] if len(parts) > idx + 2 else ""
        if slug == "all_comps":
            slug = parts[idx + 3] if len(parts) > idx + 3 else ""
        slug = slug.split("-Stats-")[0]
        return slug.replace("-", " ").title() if slug else "unknown"
    except (ValueError, IndexError):
        return "unknown"


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
# Startup helpers
# ---------------------------------------------------------------------------


async def _verify_schema(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify the database schema is compatible with this scraper version.

    Checks Alembic revision, required columns, partial index predicate,
    and fn_notify_all_due existence. Does NOT apply migrations.

    Raises:
        RuntimeError: with an actionable message if any check fails.
    """
    import sqlalchemy as _sa

    async with get_session(session_factory) as session:
        # 1. Alembic revision — must be p56a or p57a
        try:
            result = await session.execute(
                _sa.text("SELECT version_num FROM alembic_version LIMIT 1")
            )
            row = result.one_or_none()
        except Exception as exc:
            raise RuntimeError(
                "Cannot read alembic_version. Run: uv run alembic upgrade p57a"
            ) from exc

        if row is None:
            raise RuntimeError(
                "No Alembic revision applied. Run: uv run alembic upgrade p57a"
            )

        current = row[0]
        if current not in {"p56a", "p57a"}:
            raise RuntimeError(
                f"Schema revision {current!r} is not compatible with this scraper. "
                "Required: p57a (or p56a). Run: uv run alembic upgrade p57a"
            )

        # 2. Required columns on tbl_player_urls
        required = {"id", "url", "status", "retry_count", "fk_player",
                    "url_type", "next_scrape_at", "priority"}
        result = await session.execute(
            _sa.text(
                "SELECT column_name FROM information_schema.columns"
                " WHERE table_schema = 'sch_fbref_backend'"
                "   AND table_name = 'tbl_player_urls'"
            )
        )
        existing = {r[0] for r in result.fetchall()}
        missing = required - existing
        if missing:
            raise RuntimeError(
                f"tbl_player_urls is missing columns: {sorted(missing)}. "
                "Run: uv run alembic upgrade p57a"
            )

        # 3. ix_player_urls_due must include PENDING in its predicate
        result = await session.execute(
            _sa.text(
                "SELECT indexdef FROM pg_indexes"
                " WHERE schemaname = 'sch_fbref_backend'"
                "   AND indexname = 'ix_player_urls_due'"
            )
        )
        idx_row = result.one_or_none()
        if idx_row is None or "PENDING" not in idx_row[0]:
            raise RuntimeError(
                "ix_player_urls_due has wrong predicate or does not exist. "
                "Run: uv run alembic upgrade p57a"
            )

        # 4. fn_notify_all_due must exist
        result = await session.execute(
            _sa.text(
                "SELECT 1 FROM pg_proc WHERE proname = 'fn_notify_all_due' LIMIT 1"
            )
        )
        if result.one_or_none() is None:
            raise RuntimeError(
                "fn_notify_all_due function not found. "
                "Run: uv run alembic upgrade p57a"
            )


async def _startup_drain(
    session_factory: async_sessionmaker[AsyncSession],
    batch_size: int = 200,
) -> int:
    """Seed scrape_queue with all currently-due player_info URLs.

    Uses a LEFT JOIN predicate so that only genuinely schedulable registry rows
    are selected: those with no existing queue row, or whose existing queue row
    is DONE. Rows with PENDING, IN_PROGRESS, or FAILED queue rows are excluded.

    Terminates when no eligible candidates remain (RETURNING count == 0).

    Returns:
        Total number of rows inserted or reactivated.
    """
    total = 0
    while True:
        async with get_session(session_factory) as session:
            result = await session.execute(
                sa.text(
                    """
                    INSERT INTO sch_fbref_infra.scrape_queue
                        (url, domain, status, job_type, fk_url_registry_id)
                    SELECT bpu.url, 'fbref.com', 'PENDING', 'player_info', bpu.id
                    FROM sch_fbref_backend.tbl_player_urls bpu
                    LEFT JOIN sch_fbref_infra.scrape_queue sq
                           ON sq.fk_url_registry_id = bpu.id
                          AND sq.job_type = 'player_info'
                    WHERE bpu.url_type = 'profile'
                      AND bpu.status IN ('PENDING', 'ACTIVE')
                      AND bpu.next_scrape_at <= now()
                      AND (sq.id IS NULL OR sq.status = 'DONE')
                    ORDER BY bpu.priority ASC, bpu.next_scrape_at ASC, bpu.id ASC
                    LIMIT :batch_size
                    ON CONFLICT ON CONSTRAINT uq_scrape_queue_url_job_type
                    DO UPDATE SET
                        status             = 'PENDING',
                        completed_at       = NULL,
                        locked_at          = NULL,
                        error_message      = NULL,
                        retry_count        = 0,
                        fk_url_registry_id = EXCLUDED.fk_url_registry_id
                    WHERE scrape_queue.status = 'DONE'
                    RETURNING scrape_queue.id
                    """
                ),
                {"batch_size": batch_size},
            )
            n = len(result.fetchall())
            await session.commit()

        if n == 0:
            break
        total += n

    return total


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


async def main(workers: int | None = None) -> None:
    if workers is None:
        parser = argparse.ArgumentParser(description="Scrape FBRef player info pages.")
        parser.add_argument(
            "--workers",
            metavar="N",
            type=int,
            default=1,
            choices=range(1, 26),
            help="Number of parallel worker coroutines (1–25, default: 1).",
        )
        args = parser.parse_args()
        workers = args.workers

    settings = Settings()  # type: ignore[call-arg]

    assert workers is not None
    settings.db.pool_size = max(workers * 2, settings.db.pool_size)

    session_factory = create_session_factory(settings.db)

    await _verify_schema(session_factory)

    # Recover any stale IN_PROGRESS rows from a previous interrupted run
    async with get_session(session_factory) as session:
        queue_repo = PlayerInfoQueueRepository(session)
        stale = await queue_repo.recover_all_stale()
        await session.commit()
    if stale:
        logger.debug("Resumed: %d interrupted jobs restored to queue", stale)

    drained = await _startup_drain(
        session_factory, batch_size=settings.scraping.scheduling_batch_size
    )
    logger.info("Startup drain complete: %d jobs scheduled", drained)

    async with get_session(session_factory) as session:
        result = await session.execute(
            sa.text(
                "SELECT count(*) FROM sch_fbref_infra.scrape_queue"
                " WHERE job_type='player_info' AND status='PENDING'"
            )
        )
        pending_total = result.scalar() or 0
        result = await session.execute(
            sa.text("SELECT count(*) FROM sch_fbref_shared.tbl_player_info")
        )
        already_done = int(result.scalar() or 0)

    fetch_gate = asyncio.Semaphore(2)

    valid_countries = await _load_country_ids(session_factory)
    country_name_cache = await _load_country_name_cache(session_factory)
    position_cache: dict[str, int] = {}

    logger.info(
        "Launching %d worker(s)… (%d done, %d pending, %d total)",
        workers,
        already_done,
        pending_total,
        already_done + pending_total,
    )

    worker_labels: dict[int, str] = {}
    worker_counts: dict[int, int] = {}
    stop_event = asyncio.Event()

    shared_display = XvfbDisplay()
    t0 = time.monotonic()
    try:
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
            if settings.scraping.player_info_dispatch_buffer_enabled:
                _dispatch_buffer = BoundedCandidateBuffer(
                    maxsize=settings.scraping.player_info_dispatch_buffer_size
                )

                async def _peek_pending() -> list[int]:
                    async with get_session(session_factory) as _peek_session:
                        _peek_repo = PlayerInfoQueueRepository(_peek_session)
                        _ids = await _peek_repo.peek_pending_ids(
                            limit=(
                                settings.scraping.player_info_dispatch_buffer_prefetch
                            )
                        )
                        await _peek_session.commit()
                    return _ids

                _producer = CandidateProducer(
                    peek_fn=_peek_pending,
                    buffer=_dispatch_buffer,
                    n_workers=workers,
                    poll_interval=(
                        settings.scraping.player_info_dispatch_buffer_poll_interval
                    ),
                )
                _producer_task = asyncio.create_task(
                    _producer.run(), name="dispatch-producer"
                )
                _worker_instances = [
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
                        max_queue_retries=settings.scraping.max_queue_retries,
                        display=shared_display,
                    )
                    for i in range(workers)
                ]
                try:
                    results = await asyncio.gather(
                        *[
                            w.run_buffered(_dispatch_buffer)
                            for w in _worker_instances
                        ],
                        return_exceptions=True,
                    )
                finally:
                    _producer.request_stop()
                    await _producer_task
            else:
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
                            max_queue_retries=settings.scraping.max_queue_retries,
                            display=shared_display,
                        ).run()
                        for i in range(workers)
                    ],
                    return_exceptions=True,
                )
            stop_event.set()
            await display_task
    finally:
        shared_display.stop()
    elapsed = time.monotonic() - t0
    total = sum(r for r in results if isinstance(r, int))
    rate = total / elapsed if elapsed > 0 else 0
    eta_hours = (pending_total - total) / (rate * 3600) if rate > 0 else float("inf")
    logger.info(
        "Done. workers=%d | scraped=%d | elapsed=%.1fs"
        " | rate=%.2f/s | ETA full run=%.1fh",
        workers,
        total,
        elapsed,
        rate,
        eta_hours,
    )


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
