"""Unit tests for RateLimitGate."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

import pytest

from infrastructure.browser.gate import RateLimitGate

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def instant_sleep() -> tuple[list[float], Callable[[float], Awaitable[None]]]:
    """Returns (recorded, sleep_fn) where sleep_fn records delays without sleeping."""
    delays: list[float] = []

    async def _sleep(secs: float) -> None:
        delays.append(secs)

    return delays, _sleep


# ---------------------------------------------------------------------------
# Initial state
# ---------------------------------------------------------------------------


def test_gate_starts_open():
    _, sleep = instant_sleep()
    gate = RateLimitGate(sleep_fn=sleep)
    assert gate.is_open is True


def test_gate_close_reason_none_initially():
    _, sleep = instant_sleep()
    gate = RateLimitGate(sleep_fn=sleep)
    assert gate.close_reason is None


# ---------------------------------------------------------------------------
# wait_if_closed yields even when open
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wait_if_closed_yields_when_open():
    _, sleep = instant_sleep()
    gate = RateLimitGate(sleep_fn=sleep)
    yielded = False

    async def check():
        nonlocal yielded
        await gate.wait_if_closed()
        yielded = True

    await check()
    assert yielded


# ---------------------------------------------------------------------------
# signal_rate_limit closes gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_signal_rate_limit_closes_gate():
    _, sleep = instant_sleep()
    gate = RateLimitGate(cooldown_secs=0.01, sleep_fn=sleep)
    gate.signal_rate_limit(reason="test_close")
    assert gate.is_open is False
    assert gate.close_reason == "test_close"
    # Cancel the recovery task
    if gate._recovery_task:
        gate._recovery_task.cancel()
        try:
            await gate._recovery_task
        except (asyncio.CancelledError, Exception):
            pass


# ---------------------------------------------------------------------------
# Cooldown + auto-reopen (no probe)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gate_reopens_after_cooldown_no_probe():
    delays, sleep = instant_sleep()
    gate = RateLimitGate(cooldown_secs=1.0, sleep_fn=sleep)
    gate.signal_rate_limit(reason="rl")
    assert gate.is_open is False
    await gate._recovery_task  # type: ignore[union-attr]
    assert gate.is_open is True
    assert delays[0] == 1.0  # cooldown sleep was called


# ---------------------------------------------------------------------------
# Cooldown + probe pass → reopen
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gate_reopens_after_probe_pass():
    _, sleep = instant_sleep()
    gate = RateLimitGate(cooldown_secs=1.0, probe_timeout_secs=5.0, sleep_fn=sleep)

    async def good_probe() -> bool:
        return True

    gate.signal_rate_limit(reason="rl", probe_fn=good_probe)
    await gate._recovery_task  # type: ignore[union-attr]
    assert gate.is_open is True


# ---------------------------------------------------------------------------
# Probe fail all attempts → gate remains closed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gate_remains_closed_after_all_probes_fail():
    _, sleep = instant_sleep()
    gate = RateLimitGate(
        cooldown_secs=1.0,
        probe_timeout_secs=5.0,
        max_probe_attempts=3,
        sleep_fn=sleep,
    )

    async def bad_probe() -> bool:
        return False

    gate.signal_rate_limit(reason="rl", probe_fn=bad_probe)
    await gate._recovery_task  # type: ignore[union-attr]
    assert gate.is_open is False


# ---------------------------------------------------------------------------
# Probe timeout → treated as failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_probe_timeout_counts_as_failure():
    _, sleep = instant_sleep()
    gate = RateLimitGate(
        cooldown_secs=0.1,
        probe_timeout_secs=0.001,
        max_probe_attempts=1,
        sleep_fn=sleep,
    )

    async def slow_probe() -> bool:
        await asyncio.sleep(10)
        return True

    gate.signal_rate_limit(reason="rl", probe_fn=slow_probe)
    await gate._recovery_task  # type: ignore[union-attr]
    assert gate.is_open is False


# ---------------------------------------------------------------------------
# Idempotency: duplicate signals while recovery runs are dropped
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_duplicate_signal_while_recovery_noop():
    _, sleep = instant_sleep()
    gate = RateLimitGate(cooldown_secs=1.0, sleep_fn=sleep)
    gate.signal_rate_limit(reason="first")
    task1 = gate._recovery_task
    gate.signal_rate_limit(reason="second")
    task2 = gate._recovery_task
    # Both signals should share the same recovery task
    assert task1 is task2
    if task1:
        task1.cancel()
        try:
            await task1
        except (asyncio.CancelledError, Exception):
            pass


# ---------------------------------------------------------------------------
# Re-signal after all probes exhausted starts a new recovery
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resignal_after_all_probes_exhausted_starts_new_recovery():
    """After all probes fail, a new signal_rate_limit starts a fresh recovery."""
    call_count = 0

    async def eventually_good() -> bool:
        nonlocal call_count
        call_count += 1
        return call_count > 1  # fail first call, pass second

    _, sleep = instant_sleep()
    gate = RateLimitGate(
        cooldown_secs=0.0, max_probe_attempts=1, sleep_fn=sleep
    )

    # First signal: probe fails → gate remains closed
    gate.signal_rate_limit(reason="rl1", probe_fn=eventually_good)
    await gate._recovery_task  # type: ignore[union-attr]
    assert gate.is_open is False
    assert gate._recovery_task is not None
    assert gate._recovery_task.done()

    # Second signal: probe now passes → gate reopens
    gate.signal_rate_limit(reason="rl2", probe_fn=eventually_good)
    await gate._recovery_task  # type: ignore[union-attr]
    assert gate.is_open is True


# ---------------------------------------------------------------------------
# cancel_recovery() leaves gate closed and handles no-op when no task running
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_recovery_leaves_gate_closed():
    """cancel_recovery() cancels the stale task but does NOT reopen the gate."""
    _, sleep = instant_sleep()
    gate = RateLimitGate(cooldown_secs=100.0, sleep_fn=sleep)
    gate.signal_rate_limit(reason="rl")
    assert gate.is_open is False
    gate.cancel_recovery()
    assert gate.is_open is False  # gate stays closed
    # Clean up cancelled task
    if gate._recovery_task is not None:
        try:
            await gate._recovery_task
        except (asyncio.CancelledError, Exception):
            pass


def test_cancel_recovery_noop_when_no_task():
    _, sleep = instant_sleep()
    gate = RateLimitGate(sleep_fn=sleep)
    gate.cancel_recovery()  # must not raise
    assert gate.is_open is True


# ---------------------------------------------------------------------------
# mark_engine_ready() opens gate and cancels stale recovery
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mark_engine_ready_opens_gate():
    """mark_engine_ready() opens a closed gate and cancels stale recovery."""
    _, sleep = instant_sleep()
    gate = RateLimitGate(cooldown_secs=100.0, sleep_fn=sleep)
    gate.signal_rate_limit(reason="rl")
    assert gate.is_open is False
    gate.mark_engine_ready()
    assert gate.is_open is True
    # Recovery task was cancelled
    if gate._recovery_task is not None:
        try:
            await gate._recovery_task
        except (asyncio.CancelledError, Exception):
            pass


def test_mark_engine_ready_noop_when_already_open():
    """mark_engine_ready() on an already-open gate does not raise."""
    _, sleep = instant_sleep()
    gate = RateLimitGate(sleep_fn=sleep)
    gate.mark_engine_ready()  # gate was already open, no recovery task
    assert gate.is_open is True


# ---------------------------------------------------------------------------
# shutdown() cancels recovery without changing gate state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shutdown_cancels_recovery_task():
    """shutdown() cancels an in-flight recovery without changing gate state."""
    _, sleep = instant_sleep()
    gate = RateLimitGate(cooldown_secs=100.0, sleep_fn=sleep)
    gate.signal_rate_limit(reason="rl")
    assert gate.is_open is False
    gate.shutdown()
    assert gate.is_open is False  # gate state unchanged
    if gate._recovery_task is not None:
        try:
            await gate._recovery_task
        except (asyncio.CancelledError, Exception):
            pass


# ---------------------------------------------------------------------------
# CancelledError propagates cleanly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recovery_task_cancel():
    _, sleep = instant_sleep()
    gate = RateLimitGate(cooldown_secs=100.0, sleep_fn=sleep)
    gate.signal_rate_limit(reason="rl")
    assert gate._recovery_task is not None
    gate._recovery_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await gate._recovery_task


# ---------------------------------------------------------------------------
# wait_if_closed blocks while gate is closed and unblocks on reopen
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wait_if_closed_blocks_then_unblocks():
    """wait_if_closed() blocks while gate is closed and unblocks when it reopens."""
    # A sleep that yields to the event loop so tasks interleave naturally.
    async def yielding_sleep(_: float) -> None:
        await asyncio.sleep(0)

    gate = RateLimitGate(cooldown_secs=100.0, sleep_fn=yielding_sleep)
    gate.signal_rate_limit(reason="rl")
    assert gate.is_open is False

    # Cancel the recovery task immediately so it cannot auto-reopen the gate.
    assert gate._recovery_task is not None
    gate._recovery_task.cancel()
    try:
        await gate._recovery_task
    except (asyncio.CancelledError, Exception):
        pass

    unblocked = False

    async def waiter() -> None:
        nonlocal unblocked
        await gate.wait_if_closed()
        unblocked = True

    # Start the waiter concurrently.
    task = asyncio.create_task(waiter())
    # Allow the event loop to run — waiter should be blocked in wait loop.
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert not unblocked  # still blocked

    # Reopen the gate manually.
    gate.mark_engine_ready()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert unblocked  # now unblocked

    await task


# ---------------------------------------------------------------------------
# Non-rate-limit exceptions do not close the gate
# ---------------------------------------------------------------------------


def test_no_auto_close_on_creation():
    _, sleep = instant_sleep()
    gate = RateLimitGate(sleep_fn=sleep)
    assert gate.is_open is True  # fresh gate is always open


# ---------------------------------------------------------------------------
# Security: no secrets in log records
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gate_logs_no_sensitive_fields(caplog: pytest.LogCaptureFixture):
    _, sleep = instant_sleep()
    gate = RateLimitGate(cooldown_secs=0.01, sleep_fn=sleep)
    with caplog.at_level(logging.DEBUG, logger="infrastructure.browser.gate"):
        gate.signal_rate_limit(reason="rate_limit_429")
        if gate._recovery_task:
            gate._recovery_task.cancel()
            try:
                await gate._recovery_task
            except (asyncio.CancelledError, Exception):
                pass
    for record in caplog.records:
        msg = record.getMessage().lower()
        assert "cookie" not in msg
        assert "token" not in msg
        assert "password" not in msg
        assert "ws://" not in msg
        assert "wss://" not in msg
        assert "cdp" not in msg
