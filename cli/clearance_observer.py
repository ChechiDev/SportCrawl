"""RealClearanceObserver — polls an injectable getter until clearance is obtained."""

from __future__ import annotations

import time
from collections.abc import Callable

from cli.smoke_clearance_real import ClearanceResult

POLL_INTERVAL_SECONDS: float = 1.0


class RealClearanceObserver:
    """Satisfies the ClearanceObserver protocol for the real clearance harness.

    All external interactions are injectable for deterministic testing.
    """

    def __init__(
        self,
        clearance_getter: Callable[[], ClearanceResult | None],
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._clearance_getter = clearance_getter
        self._clock = clock
        self._sleeper = sleeper

    def observe(self, timeout_s: int) -> ClearanceResult:
        """Poll clearance_getter until obtained=True or deadline exceeded.

        Returns the ClearanceResult unchanged on success.
        Returns ClearanceResult(obtained=False, expires_at=None, clearance_class="")
        on timeout.
        """
        deadline = self._clock() + timeout_s

        while self._clock() < deadline:
            result = self._clearance_getter()
            if result is not None and result.obtained:
                return result
            self._sleeper(POLL_INTERVAL_SECONDS)

        return ClearanceResult(obtained=False, expires_at=None, clearance_class="")
