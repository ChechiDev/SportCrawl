"""Rate-limit execution gate for buffered player_info mode.

Shared gate object. Workers check is_open before navigating.
A single rate-limit signal closes the gate, runs a bounded cooldown,
optionally probes for readiness using an engine.warmup() call, then reopens.

No DB dependency. No secrets logged.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

_log = logging.getLogger(__name__)

_POLL_INTERVAL: float = 1.0
_MAX_PROBE_BACKOFF_SECS: float = 300.0


class RateLimitGate:
    """Shared execution gate for buffered player_info mode.

    Workers call wait_if_closed() before navigation. Any worker catching
    a RateLimitError calls signal_rate_limit() with an optional probe_fn.
    signal_rate_limit() is idempotent while recovery is in progress.

    After cooldown completes, the gate optionally probes readiness using
    probe_fn (expected to call engine.warmup()). On probe success the gate
    reopens. On probe failure it backs off and retries up to
    max_probe_attempts times; if all fail the gate remains closed and
    signal_rate_limit() must be called again by the next rate-limit event.

    Args:
        cooldown_secs: Seconds to wait after a rate-limit signal before probing.
        probe_timeout_secs: Per-probe timeout in seconds.
        max_probe_attempts: Number of probe attempts before giving up.
        sleep_fn: Async sleep callable; defaults to asyncio.sleep. Injected in tests.
    """

    def __init__(
        self,
        cooldown_secs: float = 60.0,
        probe_timeout_secs: float = 30.0,
        max_probe_attempts: int = 3,
        sleep_fn: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._open = True
        self._close_reason: str | None = None
        self._close_time: float | None = None
        self._cooldown_secs = cooldown_secs
        self._probe_timeout_secs = probe_timeout_secs
        self._max_probe_attempts = max_probe_attempts
        self._sleep: Callable[[float], Awaitable[None]] = (
            sleep_fn if sleep_fn is not None else asyncio.sleep
        )
        self._recovery_task: asyncio.Task[None] | None = None

    @property
    def is_open(self) -> bool:
        return self._open

    @property
    def close_reason(self) -> str | None:
        return self._close_reason

    async def wait_if_closed(self) -> None:
        """Always yield to event loop; block until open if currently closed."""
        await asyncio.sleep(0)
        while not self._open:
            await self._sleep(_POLL_INTERVAL)

    def signal_rate_limit(
        self,
        reason: str = "rate_limit",
        probe_fn: Callable[[], Awaitable[bool]] | None = None,
    ) -> None:
        """Close the gate and schedule cooldown+probe recovery.

        Must be called from within a running asyncio event loop because it
        calls asyncio.create_task() to schedule the recovery coroutine.

        Idempotent: duplicate signals while a recovery task is running are
        silently dropped to prevent overlapping cooldown/probe tasks.
        """
        if (
            not self._open
            and self._recovery_task is not None
            and not self._recovery_task.done()
        ):
            _log.debug(
                "rate_limit_gate: already closed (recovery running), ignoring"
            )
            return
        self._open = False
        self._close_reason = reason
        self._close_time = time.monotonic()
        _log.warning("rate_limit_gate: CLOSED | reason=%s", reason)
        self._recovery_task = asyncio.create_task(
            self._run_recovery(probe_fn),
            name="rate-limit-gate-recovery",
        )

    async def _run_recovery(
        self,
        probe_fn: Callable[[], Awaitable[bool]] | None,
    ) -> None:
        try:
            _log.info(
                "rate_limit_gate: cooldown started (%.0fs)", self._cooldown_secs
            )
            await self._sleep(self._cooldown_secs)
            _log.info("rate_limit_gate: cooldown complete")

            if probe_fn is None:
                self._open = True
                _log.info("rate_limit_gate: REOPENED (no probe configured)")
                return

            for attempt in range(1, self._max_probe_attempts + 1):
                ready = False
                try:
                    ready = await asyncio.wait_for(
                        probe_fn(), timeout=self._probe_timeout_secs
                    )
                except TimeoutError:
                    _log.warning(
                        "rate_limit_gate: probe TIMEOUT (attempt %d/%d)",
                        attempt,
                        self._max_probe_attempts,
                    )
                except Exception as _exc:  # noqa: BLE001
                    _log.warning(
                        "rate_limit_gate: probe EXCEPTION (attempt %d/%d): %s",
                        attempt,
                        self._max_probe_attempts,
                        type(_exc).__name__,
                    )

                if ready:
                    self._open = True
                    _log.info(
                        "rate_limit_gate: REOPENED (probe passed, attempt %d/%d)",
                        attempt,
                        self._max_probe_attempts,
                    )
                    return

                _log.warning(
                    "rate_limit_gate: probe FAILED (attempt %d/%d)",
                    attempt,
                    self._max_probe_attempts,
                )
                if attempt < self._max_probe_attempts:
                    backoff = min(self._cooldown_secs, _MAX_PROBE_BACKOFF_SECS)
                    _log.info(
                        "rate_limit_gate: backing off %.0fs before next probe",
                        backoff,
                    )
                    await self._sleep(backoff)

            _log.error(
                "rate_limit_gate: all %d probes failed — gate remains CLOSED",
                self._max_probe_attempts,
            )
        except asyncio.CancelledError:
            _log.debug("rate_limit_gate: recovery task cancelled")
            raise

    def cancel_recovery(self) -> None:
        """Cancel an in-flight recovery task without reopening the gate.

        Called when the engine that supplied the probe_fn is torn down.
        Cancelling prevents exhausting probe attempts against a dead engine.
        The gate remains CLOSED until the next engine proves readiness via
        mark_engine_ready().
        """
        if self._recovery_task is not None and not self._recovery_task.done():
            self._recovery_task.cancel()
        _log.debug("rate_limit_gate: recovery task cancelled (engine teardown), gate remains CLOSED")  # noqa: E501

    def mark_engine_ready(self) -> None:
        """Open the gate after a new engine session has proven readiness.

        Called after a successful on_browser_ready()/warmup() so workers can
        resume navigation. Also cancels any residual recovery task from a
        previous engine session.
        """
        if self._recovery_task is not None and not self._recovery_task.done():
            self._recovery_task.cancel()
        self._open = True
        _log.info("rate_limit_gate: REOPENED (new engine ready via warmup)")

    def shutdown(self) -> None:
        """Cancel any in-flight recovery task on process exit (no gate state change)."""
        if self._recovery_task is not None and not self._recovery_task.done():
            self._recovery_task.cancel()
        _log.debug("rate_limit_gate: shutdown, recovery task cancelled if running")
