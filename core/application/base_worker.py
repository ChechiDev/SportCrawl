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
import time
from abc import ABC, abstractmethod
from typing import Any, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class CooldownRequired(Exception):
    """Raised by run_claim_loop when retries are exhausted. BaseWorker runs cooldown."""


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
    def _build_engine(self) -> _BrowserEngine:
        """Return an async context manager that yields the browser engine."""

    # -------------------------------------------------------------------------
    # Abstract: the ENTIRE inner claim loop
    # -------------------------------------------------------------------------

    @abstractmethod
    async def run_claim_loop(self, engine: Any) -> int:
        """Drain jobs for one browser session.

        Returns:
            >= 0  — queue exhausted; return value is the count processed this session.
                    BaseWorker will stop the outer loop and return self._processed.
            -1    — browser must restart; outer loop re-enters with a new engine.

        Implementations:
        - Update self._processed, self._counts[self._worker_id], self._labels[...].
        - Own retries and mark_done / mark_failed via self._session_factory.
        - On BrowserException: return -1 (triggers browser restart).
        - On queue empty: return self._processed (stop).
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

        _MAX_RESTARTS = 5
        restart_count = 0

        while True:
            # --- Phase 1: browser start (failures count toward _MAX_RESTARTS) ---
            try:
                async with self._build_engine() as engine:
                    # --- Phase 2: inner loop (browser running; errors restart it) ---
                    try:
                        restart_count = 0  # ADR-4: reset on successful browser start
                        await self.on_browser_ready(engine)
                        loop_result = await self.run_claim_loop(engine)
                    except CooldownRequired:
                        self._labels[self._worker_id] = (
                            f"__cooldown__{time.monotonic() + 60}"
                        )
                        await asyncio.sleep(60)
                        continue
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        logger.error(exc, exc_info=True)
                        self._labels[self._worker_id] = "unexpected error — restarting"
                        await asyncio.sleep(5)
                        continue
                    if loop_result >= 0:
                        return self._processed
                    # loop_result == -1 — outer while True opens a new browser session.

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
