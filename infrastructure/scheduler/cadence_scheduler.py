"""CadenceScheduler — periodic tick that fires fn_notify_all_due().

Calls the PostgreSQL function every ``interval_seconds`` (default 60).
The function scans all sch_fbref_backend URL tables for rows whose
next_scrape_at <= now() and emits NOTIFY payloads on the
``fbref_scrape_due`` channel, which PgNotifyListener picks up.

Poll fallback: on startup, one immediate tick ensures any rows that
became due while the daemon was down are triggered before the first
regular interval fires.
"""

from __future__ import annotations

import asyncio
import logging

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger(__name__)

_NOTIFY_SQL = sa.text("SELECT sch_fbref_backend.fn_notify_all_due()")


class CadenceScheduler:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        interval_seconds: int = 60,
    ) -> None:
        self._session_factory = session_factory
        self._interval = interval_seconds
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        """Run the scheduler loop until stop() is called."""
        logger.info("CadenceScheduler started (interval=%ds)", self._interval)
        await self._tick()
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self._interval,
                )
            except asyncio.TimeoutError:
                await self._tick()
        logger.info("CadenceScheduler stopped")

    async def stop(self) -> None:
        self._stop_event.set()

    async def _tick(self) -> None:
        try:
            async with self._session_factory() as session:
                await session.execute(_NOTIFY_SQL)
                await session.commit()
            logger.info("CadenceScheduler tick: fn_notify_all_due() called")
        except Exception:
            logger.exception("CadenceScheduler tick failed — will retry next interval")
