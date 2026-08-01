"""Warm browser pool — fixed-size supervised browser slot pool for scraping."""
from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from typing import Protocol

_log = logging.getLogger(__name__)


class BrowserSlotEngine(Protocol):
    """Engine interface required by WorkerSlot.

    The slot owns the engine lifecycle: factory creates it, the slot starts
    and warms it, and the finally block closes it. claim_loop_fn receives
    the engine for use but must NOT close it — doing so causes double-close.
    """

    async def start(self) -> None: ...
    async def warmup(self, readiness_url: str) -> None: ...
    async def close(self) -> None: ...


class BackoffPolicy:
    """Bounded exponential backoff with configurable jitter."""

    def __init__(
        self,
        base: float = 2.0,
        factor: float = 2.0,
        max_delay: float = 120.0,
        jitter_fn: Callable[[], float] | None = None,
    ) -> None:
        self._base = base
        self._factor = factor
        self._max_delay = max_delay
        self._jitter_fn = (
            jitter_fn if jitter_fn is not None else lambda: random.uniform(0.0, 1.0)
        )

    def compute(self, attempt: int) -> float:
        """Delay for attempt (1-based), capped at max_delay plus jitter."""
        delay = min(self._base * (self._factor ** (attempt - 1)), self._max_delay)
        return delay + self._jitter_fn()


class WorkerSlot:
    """One warm browser slot with supervised lifecycle."""

    def __init__(
        self,
        slot_id: int,
        engine_factory: Callable[[], BrowserSlotEngine],
        claim_loop_fn: Callable[[BrowserSlotEngine], Awaitable[int]],
        readiness_url: str,
        start_semaphore: asyncio.Semaphore,
        warmup_semaphore: asyncio.Semaphore,
        startup_jitter_fn: Callable[[], float],
        browser_backoff: BackoffPolicy,
        task_backoff: BackoffPolicy,
        sleep_fn: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self.slot_id = slot_id
        self._engine_factory = engine_factory
        self._claim_loop_fn = claim_loop_fn
        self._readiness_url = readiness_url
        self._start_semaphore = start_semaphore
        self._warmup_semaphore = warmup_semaphore
        self._startup_jitter_fn = startup_jitter_fn
        self._browser_backoff = browser_backoff
        self._task_backoff = task_backoff
        self._sleep = sleep_fn if sleep_fn is not None else asyncio.sleep

    async def run(self) -> int:
        """Run the slot to completion. Returns total processed jobs."""
        await self._sleep(self._startup_jitter_fn())

        browser_failures = 0
        task_failures = 0

        while True:
            engine = self._engine_factory()
            try:
                async with self._start_semaphore:
                    await engine.start()

                async with self._warmup_semaphore:
                    await engine.warmup(self._readiness_url)

                browser_failures = 0

                result = await self._claim_loop_fn(engine)
                if result >= 0:
                    return result

                # result == -1: restart browser
                task_failures += 1
                delay = self._task_backoff.compute(task_failures)
                _log.warning(
                    "[slot-%d] claim loop requested restart; backoff %.1fs",
                    self.slot_id,
                    delay,
                )
                await self._sleep(delay)

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                browser_failures += 1
                delay = self._browser_backoff.compute(browser_failures)
                _log.warning(
                    "[slot-%d] browser error (%s); backoff %.1fs",
                    self.slot_id,
                    type(exc).__name__,
                    delay,
                )
                await self._sleep(delay)
            finally:
                await engine.close()


class WarmBrowserPool:
    """Fixed-size pool of warm browser slots for player_info scraping."""

    def __init__(
        self,
        size: int,
        slot_factory: Callable[[int], WorkerSlot],
    ) -> None:
        self._size = size
        self._slots = [slot_factory(i + 1) for i in range(size)]
        self._tasks: list[asyncio.Task[int]] = []

    async def run(self) -> list[int | BaseException]:
        """Start all slots concurrently and wait for all to complete."""
        self._tasks = [
            asyncio.create_task(slot.run(), name=f"pool-slot-{slot.slot_id}")
            for slot in self._slots
        ]
        return list(await asyncio.gather(*self._tasks, return_exceptions=True))

    async def shutdown(self) -> None:
        """Cancel all running slots and wait for cleanup."""
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)


def build_warm_pool_if_enabled(
    enabled: bool,
    pool_size: int,
    slot_factory: Callable[[int], WorkerSlot],
) -> WarmBrowserPool | None:
    """Create a WarmBrowserPool only when the feature flag is enabled."""
    if not enabled:
        return None
    return WarmBrowserPool(size=pool_size, slot_factory=slot_factory)
