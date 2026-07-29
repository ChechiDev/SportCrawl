"""PgNotifyListener — listens on a PostgreSQL NOTIFY channel and enqueues scrape jobs.

On startup the listener performs a poll fallback to enqueue any rows that became
due while it was down.  Afterwards it subscribes to the ``fbref_scrape_due``
channel and processes each incoming NOTIFY payload.

Connection loss is handled with exponential back-off (2 → 4 → 8 → 16 → 32 → 60 s).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import asyncpg
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.exceptions.scraper import SSRFError
from infrastructure.persistence.models.scrape_queue import ScrapeQueue
from infrastructure.persistence.repositories.backend_urls import BackendUrlRepository

logger = logging.getLogger(__name__)

_POLL_LIMIT = 500
_BACKOFF_STEPS = [2, 4, 8, 16, 32, 60]
_NOTIFY_CONCURRENCY = 5  # max concurrent NOTIFY handler tasks

# Maps url_type (from sch_fbref_backend) to the job_type workers consume.
# url_types without a mapping are skipped — no worker exists yet for them.
_URL_TYPE_TO_JOB_TYPE: dict[str, str] = {
    "profile": "player_info",
    "squad": "team_list",
    "clubs": "team_list",
}

_BACKEND_TABLES = [
    "tbl_player_urls",
    "tbl_team_urls",
    "tbl_competition_urls",
    "tbl_country_urls",
    "tbl_country_squad_urls",
]


class PgNotifyListener:
    """Subscribe to ``fbref_scrape_due`` and forward payloads to scrape_queue.

    Args:
        dsn: asyncpg-compatible DSN string.
        session_factory: SQLAlchemy async session factory used for queue inserts.
        channel: NOTIFY channel name (default ``fbref_scrape_due``).
    """

    def __init__(
        self,
        dsn: str,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        channel: str = "fbref_scrape_due",
    ) -> None:
        self._dsn = dsn
        self._session_factory = session_factory
        self._channel = channel
        self._running = False
        self._conn: asyncpg.Connection | None = None  # type: ignore[type-arg]
        self._sem = asyncio.Semaphore(_NOTIFY_CONCURRENCY)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Run forever — reconnects on connection loss."""
        self._running = True
        backoff_index = 0

        while self._running:
            try:
                await self._connect_and_listen()
                backoff_index = 0  # reset on clean session
            except asyncio.CancelledError:
                break
            except Exception as exc:
                if not self._running:
                    break
                delay = _BACKOFF_STEPS[min(backoff_index, len(_BACKOFF_STEPS) - 1)]
                if backoff_index >= len(_BACKOFF_STEPS) - 1:
                    logger.error(
                        "PgNotifyListener: max reconnect back-off reached (%ds). "
                        "Still retrying. Last error: %s",
                        delay,
                        exc,
                    )
                else:
                    logger.warning(
                        "PgNotifyListener: connection lost (%s). "
                        "Reconnecting in %ds…",
                        exc,
                        delay,
                    )
                backoff_index += 1
                await asyncio.sleep(delay)

    async def stop(self) -> None:
        """Graceful shutdown."""
        self._running = False
        if self._conn is not None:
            try:
                await self._conn.close()
            except Exception:
                pass
            self._conn = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _connect_and_listen(self) -> None:
        """Open a LISTEN connection, run poll fallback, then block on notifications."""
        conn: asyncpg.Connection = await asyncpg.connect(self._dsn)  # type: ignore[type-arg]
        self._conn = conn
        try:
            await conn.add_listener(self._channel, self._on_notification)
            logger.info(
                "PgNotifyListener: listening on channel %r", self._channel
            )

            # Poll fallback: enqueue rows that became due while we were down.
            await self._poll_fallback()

            # Block until the connection is closed or we are stopped.
            while self._running:
                await asyncio.sleep(1)
        finally:
            try:
                await conn.remove_listener(self._channel, self._on_notification)
            except Exception:
                pass
            try:
                await conn.close()
            except Exception:
                pass
            self._conn = None

    def _on_notification(
        self,
        __conn: asyncpg.Connection,  # type: ignore[type-arg]
        __pid: int,
        __channel: str,
        payload: str,
    ) -> None:
        """asyncpg notification callback — schedules async processing."""
        asyncio.get_running_loop().create_task(self._handle_payload(payload))

    async def _handle_payload(self, raw: str) -> None:
        """Parse a NOTIFY payload and enqueue the URL — semaphore-guarded."""
        try:
            data: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("PgNotifyListener: invalid JSON payload: %r", raw)
            return

        async with self._sem:
            async with self._session_factory() as session:
                await self._enqueue_row(
                    session=session,
                    url=data.get("url", ""),
                    url_type=data.get("url_type", "default"),
                    registry_id=data.get("id"),
                    fk_country=data.get("fk_country"),
                )
                await session.commit()

    async def _poll_fallback(self) -> None:
        """Query all five backend tables and enqueue rows already due."""
        logger.info("PgNotifyListener: running poll fallback for due rows")

        async with self._session_factory() as session:
            repo = BackendUrlRepository(session)
            for table in _BACKEND_TABLES:
                try:
                    rows = await repo.fetch_due_rows(table, limit=_POLL_LIMIT)
                except Exception as exc:
                    logger.warning(
                        "PgNotifyListener: poll fallback failed for %s: %s",
                        table,
                        exc,
                    )
                    continue
                for row in rows:
                    await self._enqueue_row(
                        session=session,
                        url=row.url,
                        url_type=row.url_type,
                        registry_id=row.id,
                        fk_country=getattr(row, "fk_country", None),
                    )
            await session.commit()

    async def _enqueue_row(
        self,
        *,
        session: AsyncSession,
        url: str,
        url_type: str,
        registry_id: int | None,
        fk_country: str | None = None,
    ) -> None:
        """Validate *url* and upsert into scrape_queue.

        ON CONFLICT DO UPDATE ensures daemon-inserted fk_url_registry_id wins over
        pipeline-seeded rows that arrive with fk_url_registry_id=NULL.
        """
        try:
            queue_row = ScrapeQueue.from_url(url)
        except SSRFError as exc:
            logger.warning(
                "PgNotifyListener: SSRF rejected url=%r (id=%s): %s",
                url,
                registry_id,
                exc,
            )
            return

        job_type = _URL_TYPE_TO_JOB_TYPE.get(url_type)
        if job_type is None:
            logger.debug("PgNotifyListener: no worker for url_type=%r — skipping", url_type)
            return

        queue_row.job_type = job_type
        queue_row.fk_url_registry_id = registry_id

        insert = pg_insert(ScrapeQueue)
        stmt = (
            insert
            .values(
                url=queue_row.url,
                domain=queue_row.domain,
                status=queue_row.status,
                job_type=queue_row.job_type,
                fk_url_registry_id=queue_row.fk_url_registry_id,
                fk_country=fk_country,
            )
            .on_conflict_do_update(
                constraint="uq_scrape_queue_url_job_type",
                set_={
                    "fk_url_registry_id": insert.excluded.fk_url_registry_id,
                    "fk_country": insert.excluded.fk_country,
                },
                where=ScrapeQueue.fk_url_registry_id.is_(None),
            )
        )
        await session.execute(stmt)

        logger.debug(
            "PgNotifyListener: enqueued %s URL id=%s",
            url_type,
            registry_id,
        )
