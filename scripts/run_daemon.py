"""sportcrawl daemon — runs CadenceScheduler and PgNotifyListener concurrently.

Usage:
    uv run python scripts/run_daemon.py

Both components run forever in the same asyncio event loop.
The daemon exits only on SIGINT / SIGTERM (Ctrl-C or systemd stop).
"""

from __future__ import annotations

import asyncio
import logging
import signal

from config.settings import Settings
from infrastructure.persistence.session import create_session_factory
from infrastructure.scheduler.cadence_scheduler import CadenceScheduler
from infrastructure.scheduler.notify_listener import PgNotifyListener

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


def _build_dsn(settings: Settings) -> str:
    db = settings.db
    return (
        f"postgresql://{db.user}:{db.password.get_secret_value()}"
        f"@{db.host}:{db.port}/{db.name}"
    )


async def _main() -> None:
    settings = Settings()  # type: ignore[call-arg]
    dsn = _build_dsn(settings)
    session_factory = create_session_factory(settings.db)

    scheduler = CadenceScheduler(session_factory, interval_seconds=60)
    listener = PgNotifyListener(dsn, session_factory)

    loop = asyncio.get_running_loop()
    stop = asyncio.Event()

    def _handle_signal() -> None:
        logger.info("Shutdown signal received")
        stop.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal)

    scheduler_task = asyncio.create_task(scheduler.start(), name="cadence-scheduler")
    listener_task = asyncio.create_task(listener.start(), name="pg-notify-listener")

    await stop.wait()

    await scheduler.stop()
    await listener.stop()
    await asyncio.gather(scheduler_task, listener_task, return_exceptions=True)
    logger.info("Daemon exited cleanly")


if __name__ == "__main__":
    asyncio.run(_main())
