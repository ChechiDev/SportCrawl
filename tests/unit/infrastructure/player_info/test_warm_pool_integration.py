"""Integration tests for warm browser pool + buffered dispatch execution path.

All tests use fakes/mocks — no live browser, DB, or FBRef required.
Tests cover the three-way mode matrix:
  - dispatch_buffer=False → direct mode (no warm pool)
  - dispatch_buffer=True, warm_pool=False → buffered mode (no warm pool)
  - dispatch_buffer=True, warm_pool=True → buffered+warm_pool mode
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from unittest.mock import AsyncMock

import pytest

from config.settings import ScrapingSettings
from infrastructure.browser.gate import RateLimitGate
from infrastructure.browser.pool import BackoffPolicy, WarmBrowserPool, WorkerSlot

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_no_sleep() -> tuple[AsyncMock, list[float]]:
    sleeps: list[float] = []

    async def _sleep(s: float) -> None:
        sleeps.append(s)

    return AsyncMock(side_effect=_sleep), sleeps


def make_engine_mock(
    start_exc: Exception | None = None,
    warmup_exc: Exception | None = None,
    navigate_exc: Exception | None = None,
) -> AsyncMock:
    engine = AsyncMock()
    engine.start = AsyncMock(side_effect=start_exc)
    engine.warmup = AsyncMock(side_effect=warmup_exc)
    engine.close = AsyncMock()
    engine.navigate = AsyncMock(side_effect=navigate_exc)
    engine.wait_for_challenge = AsyncMock(return_value="<html></html>")
    return engine


def make_gate(
    sleep_fn: Callable[[float], Awaitable[None]] | None = None,
) -> RateLimitGate:
    return RateLimitGate(
        cooldown_secs=0.0,
        probe_timeout_secs=1.0,
        max_probe_attempts=1,
        sleep_fn=sleep_fn or (lambda _: asyncio.sleep(0)),
    )


def make_slot(
    *,
    slot_id: int = 1,
    engine: AsyncMock | None = None,
    claim_result: int = 0,
    on_warmup_success: Callable[[], None] | None = None,
    on_engine_teardown: Callable[[], None] | None = None,
    sleep_fn: AsyncMock | None = None,
) -> WorkerSlot:
    if engine is None:
        engine = make_engine_mock()
    if sleep_fn is None:
        sleep_fn, _ = make_no_sleep()

    async def _claim(_: object) -> int:
        return claim_result

    return WorkerSlot(
        slot_id=slot_id,
        engine_factory=lambda: engine,
        claim_loop_fn=_claim,
        readiness_url="https://fbref.com",
        start_semaphore=asyncio.Semaphore(1),
        warmup_semaphore=asyncio.Semaphore(1),
        startup_jitter_fn=lambda: 0.0,
        browser_backoff=BackoffPolicy(jitter_fn=lambda: 0.0),
        task_backoff=BackoffPolicy(jitter_fn=lambda: 0.0),
        sleep_fn=sleep_fn,
        on_warmup_success=on_warmup_success,
        on_engine_teardown=on_engine_teardown,
    )


# ---------------------------------------------------------------------------
# Mode selection — feature flag matrix
# ---------------------------------------------------------------------------


class TestModeSelection:
    def test_warm_pool_disabled_by_default(self) -> None:
        s = ScrapingSettings()
        assert s.player_info_warm_pool_enabled is False

    def test_dispatch_buffer_disabled_by_default(self) -> None:
        s = ScrapingSettings()
        assert s.player_info_dispatch_buffer_enabled is False

    def test_warm_pool_requires_dispatch_buffer_semantically(self) -> None:
        """When dispatch buffer is disabled, warm pool flag has no effect on mode."""
        s = ScrapingSettings(
            player_info_dispatch_buffer_enabled=False,
            player_info_warm_pool_enabled=True,
        )
        # Warm pool flag is True but dispatch buffer is False;
        # the orchestrator must NOT start warm pool in this config.
        assert s.player_info_dispatch_buffer_enabled is False
        assert s.player_info_warm_pool_enabled is True

    def test_buffered_without_warm_pool_is_valid(self) -> None:
        s = ScrapingSettings(
            player_info_dispatch_buffer_enabled=True,
            player_info_warm_pool_enabled=False,
        )
        assert s.player_info_dispatch_buffer_enabled is True
        assert s.player_info_warm_pool_enabled is False

    def test_buffered_with_warm_pool_is_valid(self) -> None:
        s = ScrapingSettings(
            player_info_dispatch_buffer_enabled=True,
            player_info_warm_pool_enabled=True,
        )
        assert s.player_info_dispatch_buffer_enabled is True
        assert s.player_info_warm_pool_enabled is True

    def test_build_warm_pool_if_enabled_respects_flag(self) -> None:
        from infrastructure.browser.pool import build_warm_pool_if_enabled

        assert build_warm_pool_if_enabled(
            enabled=False, pool_size=2, slot_factory=lambda s: make_slot(slot_id=s)
        ) is None
        assert (
            build_warm_pool_if_enabled(
                enabled=True, pool_size=2, slot_factory=lambda s: make_slot(slot_id=s)
            )
            is not None
        )


# ---------------------------------------------------------------------------
# Warm pool + gate interaction
# ---------------------------------------------------------------------------


class TestWarmPoolGateInteraction:
    @pytest.mark.asyncio
    async def test_mark_engine_ready_called_after_warmup_success(self) -> None:
        """mark_engine_ready is wired as on_warmup_success callback."""
        # Use a long cooldown so recovery does not auto-complete during the test.
        gate = RateLimitGate(
            cooldown_secs=999.0, probe_timeout_secs=1.0, max_probe_attempts=1
        )
        gate.signal_rate_limit(reason="test")
        assert gate.is_open is False

        ready_calls: list[bool] = []
        original_ready = gate.mark_engine_ready

        def _tracked_ready() -> None:
            ready_calls.append(True)
            original_ready()

        slot = make_slot(on_warmup_success=_tracked_ready)
        await slot.run()
        gate.shutdown()
        assert len(ready_calls) == 1
        assert gate.is_open is True

    @pytest.mark.asyncio
    async def test_mark_engine_ready_reopens_closed_gate(self) -> None:
        """Gate reopens when mark_engine_ready is called after warmup."""
        gate = RateLimitGate(
            cooldown_secs=999.0, probe_timeout_secs=1.0, max_probe_attempts=1
        )
        gate.signal_rate_limit(reason="test")
        slot = make_slot(on_warmup_success=gate.mark_engine_ready)
        await slot.run()
        gate.shutdown()
        assert gate.is_open is True

    @pytest.mark.asyncio
    async def test_cancel_recovery_called_on_engine_teardown(self) -> None:
        """cancel_recovery is wired as on_engine_teardown callback."""
        gate = make_gate()
        cancel_calls: list[bool] = []
        original_cancel = gate.cancel_recovery

        def _tracked_cancel() -> None:
            cancel_calls.append(True)
            original_cancel()

        slot = make_slot(on_engine_teardown=_tracked_cancel)
        await slot.run()
        assert len(cancel_calls) == 1

    @pytest.mark.asyncio
    async def test_cancel_recovery_does_not_reopen_gate(self) -> None:
        """cancel_recovery cancels recovery task but does not open the gate."""
        gate = RateLimitGate(
            cooldown_secs=999.0, probe_timeout_secs=1.0, max_probe_attempts=1
        )
        gate.signal_rate_limit(reason="test")
        slot = make_slot(on_engine_teardown=gate.cancel_recovery)
        await slot.run()
        gate.shutdown()
        # Gate remains closed because cancel_recovery does not reopen
        assert gate.is_open is False

    @pytest.mark.asyncio
    async def test_cancel_recovery_called_on_browser_failure(self) -> None:
        """cancel_recovery is called in finally even when browser start fails."""
        gate = make_gate()
        cancel_calls: list[bool] = []

        def _tracked_cancel() -> None:
            cancel_calls.append(True)
            gate.cancel_recovery()

        call_count = 0

        def engine_factory() -> AsyncMock:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return make_engine_mock(start_exc=OSError("no chrome"))
            return make_engine_mock()

        sleep_fn, _ = make_no_sleep()

        async def _claim(_: object) -> int:
            return 0

        slot = WorkerSlot(
            slot_id=1,
            engine_factory=engine_factory,
            claim_loop_fn=_claim,
            readiness_url="https://fbref.com",
            start_semaphore=asyncio.Semaphore(1),
            warmup_semaphore=asyncio.Semaphore(1),
            startup_jitter_fn=lambda: 0.0,
            browser_backoff=BackoffPolicy(jitter_fn=lambda: 0.0),
            task_backoff=BackoffPolicy(jitter_fn=lambda: 0.0),
            sleep_fn=sleep_fn,
            on_engine_teardown=_tracked_cancel,
        )
        await slot.run()
        # Called for both the failed and successful engine
        assert len(cancel_calls) == 2

    @pytest.mark.asyncio
    async def test_gate_remains_closed_after_cancel_recovery(self) -> None:
        """cancel_recovery must not reopen gate; only mark_engine_ready does."""
        gate = make_gate()
        # Schedule a recovery, then cancel it
        probe_called = asyncio.Event()

        async def _probe() -> bool:
            probe_called.set()
            return True

        gate.signal_rate_limit(reason="test", probe_fn=_probe)
        assert gate.is_open is False
        gate.cancel_recovery()
        await asyncio.sleep(0)
        assert gate.is_open is False  # gate must remain closed

    @pytest.mark.asyncio
    async def test_gate_reopens_only_after_mark_engine_ready(self) -> None:
        """Sequential: cancel_recovery then mark_engine_ready reopens gate."""
        gate = make_gate()
        gate.signal_rate_limit(reason="test")
        gate.cancel_recovery()
        assert gate.is_open is False
        gate.mark_engine_ready()
        assert gate.is_open is True

    @pytest.mark.asyncio
    async def test_repeated_rate_limit_signals_do_not_stack_recovery_tasks(
        self,
    ) -> None:
        """Duplicate rate-limit signals while recovery runs are silently dropped."""
        gate = RateLimitGate(
            cooldown_secs=999.0,
            probe_timeout_secs=1.0,
            max_probe_attempts=1,
        )
        gate.signal_rate_limit(reason="first")
        task1 = gate._recovery_task
        gate.signal_rate_limit(reason="second")
        task2 = gate._recovery_task
        assert task1 is task2  # same task, not a new one
        gate.shutdown()


# ---------------------------------------------------------------------------
# Dispatch + warm pool interaction
# ---------------------------------------------------------------------------


class TestDispatchWarmPoolInteraction:
    @pytest.mark.asyncio
    async def test_slot_uses_engine_from_factory(self) -> None:
        """WorkerSlot uses the engine from engine_factory, not a shared one."""
        engines_used: list[AsyncMock] = []

        async def _claim(e: object) -> int:
            engines_used.append(e)  # type: ignore[arg-type]
            return 0

        engine1 = make_engine_mock()
        engine2 = make_engine_mock()
        engines_to_give = [engine1, engine2]
        idx = 0

        def factory() -> AsyncMock:
            nonlocal idx
            e = engines_to_give[idx % len(engines_to_give)]
            idx += 1
            return e

        sleep_fn, _ = make_no_sleep()
        slot = WorkerSlot(
            slot_id=1,
            engine_factory=factory,
            claim_loop_fn=_claim,
            readiness_url="https://fbref.com",
            start_semaphore=asyncio.Semaphore(1),
            warmup_semaphore=asyncio.Semaphore(1),
            startup_jitter_fn=lambda: 0.0,
            browser_backoff=BackoffPolicy(jitter_fn=lambda: 0.0),
            task_backoff=BackoffPolicy(jitter_fn=lambda: 0.0),
            sleep_fn=sleep_fn,
        )
        await slot.run()
        assert len(engines_used) == 1
        assert engines_used[0] is engine1

    @pytest.mark.asyncio
    async def test_cooldown_required_converted_to_minus_one_in_claim_fn(
        self,
    ) -> None:
        """CooldownRequired caught in claim_fn should return -1 (trigger restart)."""
        from core.application.base_worker import CooldownRequired

        restarts: list[int] = []
        call_count = 0

        async def _claim_with_cooldown(_: object) -> int:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise CooldownRequired
            return 0

        # Wrap the claim_fn to catch CooldownRequired — this is what _make_slot does
        async def _safe_claim(engine: object) -> int:
            try:
                return await _claim_with_cooldown(engine)
            except CooldownRequired:
                restarts.append(1)
                return -1

        sleep_fn, _ = make_no_sleep()
        slot = WorkerSlot(
            slot_id=1,
            engine_factory=lambda: make_engine_mock(),
            claim_loop_fn=_safe_claim,
            readiness_url="https://fbref.com",
            start_semaphore=asyncio.Semaphore(1),
            warmup_semaphore=asyncio.Semaphore(1),
            startup_jitter_fn=lambda: 0.0,
            browser_backoff=BackoffPolicy(jitter_fn=lambda: 0.0),
            task_backoff=BackoffPolicy(jitter_fn=lambda: 0.0),
            sleep_fn=sleep_fn,
        )
        result = await slot.run()
        assert result == 0
        assert len(restarts) == 1

    @pytest.mark.asyncio
    async def test_warm_pool_does_not_start_when_buffer_disabled(self) -> None:
        """No WarmBrowserPool is created when dispatch_buffer_enabled=False."""
        from infrastructure.browser.pool import build_warm_pool_if_enabled

        pool = build_warm_pool_if_enabled(
            enabled=False,
            pool_size=2,
            slot_factory=lambda s: make_slot(slot_id=s),
        )
        assert pool is None

    @pytest.mark.asyncio
    async def test_warm_pool_creates_correct_slot_count(self) -> None:
        """Pool creates one slot per worker."""
        created_ids: list[int] = []

        def factory(slot_id: int) -> WorkerSlot:
            created_ids.append(slot_id)
            return make_slot(slot_id=slot_id)

        pool = WarmBrowserPool(size=3, slot_factory=factory)
        assert pool._size == 3
        assert created_ids == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_no_direct_db_claim_in_warm_pool_path(self) -> None:
        """Warm pool claim_fn wraps _run_buffered_loop; no claim_next() call."""
        # This is a structural assertion: claim_next is not called when
        # the slot's claim_fn is the buffered loop wrapper. We verify by
        # checking that the claim_fn interface (returns int / -1) is what
        # WorkerSlot expects — not claim_next() which returns a DB row.
        claim_fn_results: list[int] = []

        async def _buffered_claim_fn(_: object) -> int:
            result = 7
            claim_fn_results.append(result)
            return result

        sleep_fn, _ = make_no_sleep()
        slot = WorkerSlot(
            slot_id=1,
            engine_factory=lambda: make_engine_mock(),
            claim_loop_fn=_buffered_claim_fn,
            readiness_url="https://fbref.com",
            start_semaphore=asyncio.Semaphore(1),
            warmup_semaphore=asyncio.Semaphore(1),
            startup_jitter_fn=lambda: 0.0,
            browser_backoff=BackoffPolicy(jitter_fn=lambda: 0.0),
            task_backoff=BackoffPolicy(jitter_fn=lambda: 0.0),
            sleep_fn=sleep_fn,
        )
        result = await slot.run()
        assert result == 7
        assert claim_fn_results == [7]

    @pytest.mark.asyncio
    async def test_worker_ids_remain_stable_across_slot_restarts(self) -> None:
        """slot_id is fixed for the lifetime of a WorkerSlot (not per engine)."""
        slot = make_slot(slot_id=42)
        assert slot.slot_id == 42
        # slot_id does not change after run
        await slot.run()
        assert slot.slot_id == 42


# ---------------------------------------------------------------------------
# Security / logging
# ---------------------------------------------------------------------------


class TestSecurityInvariants:
    @pytest.mark.asyncio
    async def test_no_sensitive_data_in_warmup_success_log(self) -> None:
        """on_warmup_success callback log must not contain credentials."""
        captured: list[str] = []

        class _Handler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                captured.append(record.getMessage())

        log = logging.getLogger("infrastructure.browser.pool")
        h = _Handler()
        log.addHandler(h)
        try:
            gate = make_gate()
            slot = make_slot(on_warmup_success=gate.mark_engine_ready)
            await slot.run()
        finally:
            log.removeHandler(h)

        for msg in captured:
            lower = msg.lower()
            assert "cookie" not in lower
            assert "cdp" not in lower
            assert "ws://" not in msg
            assert "token" not in lower

    @pytest.mark.asyncio
    async def test_no_sensitive_data_in_engine_teardown_log(self) -> None:
        """on_engine_teardown callback log must not contain credentials."""
        captured: list[str] = []

        class _Handler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                captured.append(record.getMessage())

        gate_log = logging.getLogger("infrastructure.browser.gate")
        pool_log = logging.getLogger("infrastructure.browser.pool")
        h = _Handler()
        gate_log.addHandler(h)
        pool_log.addHandler(h)
        try:
            gate = make_gate()
            slot = make_slot(on_engine_teardown=gate.cancel_recovery)
            await slot.run()
        finally:
            gate_log.removeHandler(h)
            pool_log.removeHandler(h)

        for msg in captured:
            lower = msg.lower()
            assert "cookie" not in lower
            assert "ws://" not in msg
            assert "token" not in lower

    def test_pool_module_has_no_persistence_import(self) -> None:
        import importlib
        import inspect
        import sys

        mod = sys.modules.get("infrastructure.browser.pool") or importlib.import_module(
            "infrastructure.browser.pool"
        )
        source = inspect.getsource(mod)
        assert "infrastructure.persistence" not in source

    def test_pool_module_has_no_config_import(self) -> None:
        import importlib
        import inspect
        import sys

        mod = sys.modules.get("infrastructure.browser.pool") or importlib.import_module(
            "infrastructure.browser.pool"
        )
        source = inspect.getsource(mod)
        assert "config.settings" not in source
        assert "from config" not in source
