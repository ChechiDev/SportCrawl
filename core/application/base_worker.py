"""BaseWorker — abstract outer browser-restart skeleton (Template Method pattern).

Subclasses implement the ENTIRE inner claim loop via run_claim_loop(engine).
BaseWorker owns only: startup hook, browser lifecycle, and the outer restart loop.

ADR-1: Template Method chosen over per-job process_job because the inner loop's
browser_restart flag must break BOTH the inner attempt loop AND the outer restart
while-True. A per-job return cannot express "restart the browser now".

ADR-4: restart_count semantics — resets to 0 on every successful browser start.
max_restarts only caps consecutive browser-START failures, not total restart cycles.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@runtime_checkable
class _BrowserEngine(Protocol):
    async def __aenter__(self) -> Any: ...
    async def __aexit__(self, *args: Any) -> Any: ...


class BaseWorker[TJob](ABC):
    """Abstract worker that owns the outer browser-restart loop.

    Subclasses must implement:
        profile_dir     — path to an isolated Chrome profile for this worker
        engine_name     — display name passed to the browser engine
        _build_engine() — factory that returns an async context manager engine
        run_claim_loop(engine) — the full inner job-claim-and-process loop

    Optional hooks (default no-op):
        startup_delay()          — called once before the restart loop starts
        on_browser_ready(engine) — called after browser starts, before run_claim_loop
    """

    def __init__(
        self,
        worker_id: int,
        session_factory: async_sessionmaker[AsyncSession],
        fetch_gate: asyncio.Semaphore,
        profile_base: str,
        worker_labels: dict[int, str],
        worker_counts: dict[int, int],
    ) -> None:
        self._worker_id = worker_id
        self._session_factory = session_factory
        self._fetch_gate = fetch_gate
        self._profile_base = profile_base
        self._labels = worker_labels   # shared dict — mutated in place for live display
        self._counts = worker_counts   # shared dict — mutated in place for live display
        self._processed = 0

    # -------------------------------------------------------------------------
    # Abstract: subclass identity
    # -------------------------------------------------------------------------

    @property
    @abstractmethod
    def profile_dir(self) -> str:
        """Path to the isolated Chrome profile directory for this worker."""

    @property
    @abstractmethod
    def engine_name(self) -> str:
        """Display name passed to the browser engine for this worker."""

    @abstractmethod
    def _build_engine(self) -> Any:
        """Return an async context manager that yields the browser engine."""

    # -------------------------------------------------------------------------
    # Abstract: the ENTIRE inner claim loop
    # -------------------------------------------------------------------------

    @abstractmethod
    async def run_claim_loop(self, engine: Any) -> bool:
        """Drain jobs for one browser session.

        Returns:
            True  — queue exhausted; worker should stop (return self._processed).
            False — browser must restart; outer loop re-enters with a new engine.

        Implementations:
        - Update self._processed, self._counts[self._worker_id], self._labels[...].
        - Own retries and mark_done / mark_failed via self._session_factory.
        - On BrowserException: return False (triggers browser restart).
        - On queue empty (job is None): return True (stop) or handle step2_done.
        """

    # -------------------------------------------------------------------------
    # Hooks (default no-op — subclasses may override)
    # -------------------------------------------------------------------------

    async def startup_delay(self) -> None:
        """Called once before the outer restart loop. Default: no-op."""
        return None

    async def on_browser_ready(self, _engine: Any) -> None:
        """Called after browser starts, before run_claim_loop. Default: no-op."""
        return None

    # -------------------------------------------------------------------------
    # Template method: outer restart skeleton
    # -------------------------------------------------------------------------

    async def run(self) -> int:
        """Run the worker to completion and return the number of processed jobs."""
        logger = logging.getLogger(__name__)
        await self.startup_delay()

        max_restarts = 5
        restart_count = 0

        while True:
            browser_started = False
            try:
                async with self._build_engine() as engine:
                    browser_started = True
                    restart_count = 0  # ADR-4: reset on every successful browser start
                    await self.on_browser_ready(engine)
                    should_stop = await self.run_claim_loop(engine)
                    if should_stop:
                        return self._processed
                    # should_stop=False means run_claim_loop requested a browser restart
                    # Fall through — outer while True will open a new browser session.

            except Exception as exc:
                if not browser_started:
                    restart_count += 1
                    if restart_count >= max_restarts:
                        self._labels[self._worker_id] = "browser failed — giving up"
                        return self._processed
                    self._labels[self._worker_id] = (
                        f"browser start failed — retry {restart_count}/{max_restarts}"
                    )
                    await asyncio.sleep(10)
                    continue
                # Error after browser was running — log and restart browser.
                logger.error(exc, exc_info=True)
                self._labels[self._worker_id] = "unexpected error — restarting"
                await asyncio.sleep(5)
                continue
