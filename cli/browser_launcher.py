# cli/browser_launcher.py
"""RealBrowserLauncher — synchronous wrapper around async engine start and CDP probe."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Coroutine
from typing import Any


class RealBrowserLauncher:
    """Satisfies the BrowserLauncher protocol for the real clearance harness.

    All external interactions are injectable for testing.
    """

    def __init__(
        self,
        engine_starter: Callable[[], Coroutine[Any, Any, None]],
        cdp_probe: Callable[[], Coroutine[Any, Any, None]],
        engine_stopper: Callable[[], Coroutine[Any, Any, None]] | None = None,
        loop_runner: Callable[[Coroutine[Any, Any, Any]], Any] = asyncio.run,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._engine_starter = engine_starter
        self._cdp_probe = cdp_probe
        self._engine_stopper = engine_stopper
        self._loop_runner = loop_runner
        self._clock = clock
        self._sleeper = sleeper
        self._started: bool = False

    def start(self) -> bool:
        """Start the browser engine. Returns True on success, False on any exception."""
        try:
            self._loop_runner(self._engine_starter())
        except Exception:
            return False
        self._started = True
        return True

    def wait_cdp_ready(self, timeout_s: int) -> tuple[bool, int]:
        """Poll the CDP probe until ready or timeout.

        Returns (ready, elapsed_s). elapsed is always a non-negative int.
        """
        if not self._started:
            return False, 0

        t0 = self._clock()
        deadline = t0 + timeout_s

        while self._clock() < deadline:
            try:
                self._loop_runner(self._cdp_probe())
                elapsed = max(0, int(self._clock() - t0))
                return True, elapsed
            except Exception:
                self._sleeper(0.5)

        elapsed = max(0, int(self._clock() - t0))
        return False, elapsed

    def stop(self) -> None:
        """Stop the browser engine.

        Invokes engine_stopper if configured; no-op otherwise.
        Resets _started to False regardless of stopper outcome.
        """
        if self._engine_stopper is not None:
            try:
                self._loop_runner(self._engine_stopper())
            except Exception:
                pass
        self._started = False
