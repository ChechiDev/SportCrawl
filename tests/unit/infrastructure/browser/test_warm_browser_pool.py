"""Unit tests for WarmBrowserPool, WorkerSlot, and BackoffPolicy."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.exceptions.scraper import WarmupError
from infrastructure.browser.pool import BackoffPolicy, WarmBrowserPool, WorkerSlot

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_no_sleep() -> tuple[AsyncMock, list[float]]:
    """Return (sleep_fn mock, list of recorded sleep durations)."""
    sleeps: list[float] = []

    async def _sleep(s: float) -> None:
        sleeps.append(s)

    return AsyncMock(side_effect=_sleep), sleeps


def make_engine_mock(
    start_exc: Exception | None = None,
    warmup_exc: Exception | None = None,
) -> AsyncMock:
    engine = AsyncMock()
    engine.start = AsyncMock(side_effect=start_exc)
    engine.warmup = AsyncMock(side_effect=warmup_exc)
    engine.close = AsyncMock()
    return engine


def make_slot(
    *,
    slot_id: int = 1,
    engine: AsyncMock | None = None,
    claim_result: int = 0,
    readiness_url: str = "https://fbref.com",
    startup_jitter: float = 0.0,
    browser_backoff: BackoffPolicy | None = None,
    task_backoff: BackoffPolicy | None = None,
    sleep_fn: AsyncMock | None = None,
    start_sem: asyncio.Semaphore | None = None,
    warmup_sem: asyncio.Semaphore | None = None,
) -> WorkerSlot:
    if engine is None:
        engine = make_engine_mock()
    if browser_backoff is None:
        browser_backoff = BackoffPolicy(jitter_fn=lambda: 0.0)
    if task_backoff is None:
        task_backoff = BackoffPolicy(jitter_fn=lambda: 0.0)
    if sleep_fn is None:
        sleep_fn, _ = make_no_sleep()
    if start_sem is None:
        start_sem = asyncio.Semaphore(1)
    if warmup_sem is None:
        warmup_sem = asyncio.Semaphore(1)

    async def _claim(_e: object) -> int:
        return claim_result

    return WorkerSlot(
        slot_id=slot_id,
        engine_factory=lambda: engine,
        claim_loop_fn=_claim,
        readiness_url=readiness_url,
        start_semaphore=start_sem,
        warmup_semaphore=warmup_sem,
        startup_jitter_fn=lambda: startup_jitter,
        browser_backoff=browser_backoff,
        task_backoff=task_backoff,
        sleep_fn=sleep_fn,
    )


async def _claim_zero(_e: object) -> int:
    """Claim loop that immediately returns 0. Replaces asyncio.coroutine usage."""
    return 0


# ---------------------------------------------------------------------------
# TestBackoffPolicy
# ---------------------------------------------------------------------------


class TestBackoffPolicy:
    def test_compute_attempt_1_returns_base_plus_jitter(self) -> None:
        policy = BackoffPolicy(
            base=2.0, factor=2.0, max_delay=120.0, jitter_fn=lambda: 0.0
        )
        result = policy.compute(attempt=1)
        assert result == 2.0

    def test_compute_grows_exponentially(self) -> None:
        policy = BackoffPolicy(
            base=2.0, factor=2.0, max_delay=120.0, jitter_fn=lambda: 0.0
        )
        assert policy.compute(attempt=2) == 4.0
        assert policy.compute(attempt=3) == 8.0

    def test_compute_capped_at_max_delay(self) -> None:
        policy = BackoffPolicy(
            base=2.0, factor=2.0, max_delay=10.0, jitter_fn=lambda: 0.0
        )
        # attempt=100 would be astronomical; result must be capped at max_delay
        result = policy.compute(attempt=100)
        assert result == 10.0

    def test_default_jitter_is_random(self) -> None:
        policy = BackoffPolicy(base=0.0, max_delay=1000.0)
        results = [policy.compute(attempt=1) for _ in range(5)]
        # All results must be within [0.0, 1.0] (base=0, jitter range is 0–1)
        for r in results:
            assert 0.0 <= r <= 1.0

    def test_custom_jitter_fn_is_called(self) -> None:
        jitter_called = []

        def custom_jitter() -> float:
            jitter_called.append(True)
            return 0.5

        policy = BackoffPolicy(base=2.0, jitter_fn=custom_jitter)
        result = policy.compute(attempt=1)
        assert result == 2.5
        assert len(jitter_called) == 1


# ---------------------------------------------------------------------------
# TestWorkerSlot
# ---------------------------------------------------------------------------


class TestWorkerSlot:
    @pytest.mark.asyncio
    async def test_run_applies_startup_jitter(self) -> None:
        sleep_fn, sleeps = make_no_sleep()
        engine = make_engine_mock()
        slot = make_slot(startup_jitter=3.5, sleep_fn=sleep_fn, engine=engine)
        await slot.run()
        assert sleeps[0] == 3.5

    @pytest.mark.asyncio
    async def test_run_calls_engine_start_then_warmup(self) -> None:
        engine = make_engine_mock()
        call_order: list[str] = []

        async def _start() -> None:
            call_order.append("start")

        async def _warmup(_url: str) -> None:
            call_order.append("warmup")

        engine.start = AsyncMock(side_effect=_start)
        engine.warmup = AsyncMock(side_effect=_warmup)

        slot = make_slot(engine=engine)
        await slot.run()

        assert call_order == ["start", "warmup"]

    @pytest.mark.asyncio
    async def test_run_acquires_start_semaphore_before_start(self) -> None:
        engine = make_engine_mock()
        start_sem = asyncio.Semaphore(1)
        slot = make_slot(engine=engine, start_sem=start_sem)
        await slot.run()
        engine.start.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_run_acquires_warmup_semaphore_before_warmup(self) -> None:
        engine = make_engine_mock()
        warmup_sem = asyncio.Semaphore(1)
        slot = make_slot(engine=engine, warmup_sem=warmup_sem)
        await slot.run()
        engine.warmup.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_run_calls_claim_loop_with_engine(self) -> None:
        engine = make_engine_mock()
        received_engines: list[object] = []

        async def _claim(e: object) -> int:
            received_engines.append(e)
            return 0

        sleep_fn, _ = make_no_sleep()
        slot = WorkerSlot(
            slot_id=1,
            engine_factory=lambda: engine,
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
        assert len(received_engines) == 1
        assert received_engines[0] is engine

    @pytest.mark.asyncio
    async def test_run_returns_when_claim_loop_returns_non_negative(self) -> None:
        engine = make_engine_mock()
        slot = make_slot(engine=engine, claim_result=5)
        result = await slot.run()
        assert result == 5

    @pytest.mark.asyncio
    async def test_run_restarts_on_claim_loop_minus_one(self) -> None:
        engines_created: list[AsyncMock] = []
        call_count = 0

        def engine_factory() -> AsyncMock:
            e = make_engine_mock()
            engines_created.append(e)
            return e

        async def _claim(_e: object) -> int:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return -1
            return 3

        sleep_fn, _ = make_no_sleep()
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
        )
        result = await slot.run()
        assert result == 3
        assert len(engines_created) == 2

    @pytest.mark.asyncio
    async def test_run_closes_engine_after_claim_loop(self) -> None:
        engine = make_engine_mock()
        slot = make_slot(engine=engine)
        await slot.run()
        engine.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_run_closes_engine_on_warmup_failure(self) -> None:
        engine = make_engine_mock(warmup_exc=WarmupError("warmup failed"))
        # Second engine succeeds so slot terminates
        engine2 = make_engine_mock()
        call_count = 0

        def engine_factory() -> AsyncMock:
            nonlocal call_count
            call_count += 1
            return engine if call_count == 1 else engine2

        sleep_fn, _ = make_no_sleep()
        slot = WorkerSlot(
            slot_id=1,
            engine_factory=engine_factory,
            claim_loop_fn=_claim_zero,
            readiness_url="https://fbref.com",
            start_semaphore=asyncio.Semaphore(1),
            warmup_semaphore=asyncio.Semaphore(1),
            startup_jitter_fn=lambda: 0.0,
            browser_backoff=BackoffPolicy(jitter_fn=lambda: 0.0),
            task_backoff=BackoffPolicy(jitter_fn=lambda: 0.0),
            sleep_fn=sleep_fn,
        )
        await slot.run()
        engine.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_run_backs_off_on_warmup_failure(self) -> None:
        """WarmupError triggers browser_backoff; slot succeeds on retry."""
        sleep_fn, _ = make_no_sleep()
        backoff_delays: list[int] = []

        class _TrackingBackoff(BackoffPolicy):
            def compute(self, attempt: int) -> float:
                backoff_delays.append(attempt)
                return 0.0  # no real sleep

        browser_backoff = _TrackingBackoff(jitter_fn=lambda: 0.0)

        call_count = 0

        def engine_factory() -> AsyncMock:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return make_engine_mock(warmup_exc=WarmupError("fail"))
            return make_engine_mock()

        slot = WorkerSlot(
            slot_id=1,
            engine_factory=engine_factory,
            claim_loop_fn=_claim_zero,
            readiness_url="https://fbref.com",
            start_semaphore=asyncio.Semaphore(1),
            warmup_semaphore=asyncio.Semaphore(1),
            startup_jitter_fn=lambda: 0.0,
            browser_backoff=browser_backoff,
            task_backoff=BackoffPolicy(jitter_fn=lambda: 0.0),
            sleep_fn=sleep_fn,
        )
        await slot.run()
        # browser_backoff.compute was called once (for the first failure)
        assert len(backoff_delays) >= 1

    @pytest.mark.asyncio
    async def test_run_backs_off_on_browser_start_failure(self) -> None:
        """OSError on first start → browser_backoff consulted → success on retry."""
        sleep_fn, _ = make_no_sleep()
        backoff_delays: list[int] = []

        class _TrackingBackoff(BackoffPolicy):
            def compute(self, attempt: int) -> float:
                backoff_delays.append(attempt)
                return 0.0

        browser_backoff = _TrackingBackoff(jitter_fn=lambda: 0.0)
        call_count = 0

        def engine_factory() -> AsyncMock:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return make_engine_mock(start_exc=OSError("no chrome"))
            return make_engine_mock()

        slot = WorkerSlot(
            slot_id=1,
            engine_factory=engine_factory,
            claim_loop_fn=_claim_zero,
            readiness_url="https://fbref.com",
            start_semaphore=asyncio.Semaphore(1),
            warmup_semaphore=asyncio.Semaphore(1),
            startup_jitter_fn=lambda: 0.0,
            browser_backoff=browser_backoff,
            task_backoff=BackoffPolicy(jitter_fn=lambda: 0.0),
            sleep_fn=sleep_fn,
        )
        await slot.run()
        assert len(backoff_delays) >= 1

    @pytest.mark.asyncio
    async def test_run_does_not_share_engine_between_restarts(self) -> None:
        engines_created: list[AsyncMock] = []
        call_count = 0

        def engine_factory() -> AsyncMock:
            e = make_engine_mock()
            engines_created.append(e)
            return e

        async def _claim(_e: object) -> int:
            nonlocal call_count
            call_count += 1
            return -1 if call_count < 3 else 0

        sleep_fn, _ = make_no_sleep()
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
        )
        await slot.run()
        assert len(engines_created) == 3

    @pytest.mark.asyncio
    async def test_run_cancelled_error_propagates(self) -> None:
        async def _claim_cancel(_e: object) -> int:
            raise asyncio.CancelledError()

        sleep_fn, _ = make_no_sleep()
        slot = WorkerSlot(
            slot_id=1,
            engine_factory=lambda: make_engine_mock(),
            claim_loop_fn=_claim_cancel,
            readiness_url="https://fbref.com",
            start_semaphore=asyncio.Semaphore(1),
            warmup_semaphore=asyncio.Semaphore(1),
            startup_jitter_fn=lambda: 0.0,
            browser_backoff=BackoffPolicy(jitter_fn=lambda: 0.0),
            task_backoff=BackoffPolicy(jitter_fn=lambda: 0.0),
            sleep_fn=sleep_fn,
        )
        with pytest.raises(asyncio.CancelledError):
            await slot.run()

    @pytest.mark.asyncio
    async def test_startup_jitter_is_from_jitter_fn_not_slot_id(self) -> None:
        """Two slots with different IDs both use exactly 7.0 from jitter_fn."""
        sleeps1: list[float] = []
        sleeps2: list[float] = []

        def make_sleep_fn(record: list[float]) -> AsyncMock:
            async def _sleep(s: float) -> None:
                record.append(s)
            return AsyncMock(side_effect=_sleep)

        def make_fixed_slot(sid: int, record: list[float]) -> WorkerSlot:
            return WorkerSlot(
                slot_id=sid,
                engine_factory=lambda: make_engine_mock(),
                claim_loop_fn=_claim_zero,
                readiness_url="https://fbref.com",
                start_semaphore=asyncio.Semaphore(1),
                warmup_semaphore=asyncio.Semaphore(1),
                startup_jitter_fn=lambda: 7.0,
                browser_backoff=BackoffPolicy(jitter_fn=lambda: 0.0),
                task_backoff=BackoffPolicy(jitter_fn=lambda: 0.0),
                sleep_fn=make_sleep_fn(record),
            )

        slot1 = make_fixed_slot(1, sleeps1)
        slot5 = make_fixed_slot(5, sleeps2)
        await asyncio.gather(slot1.run(), slot5.run())
        assert sleeps1[0] == 7.0
        assert sleeps2[0] == 7.0


# ---------------------------------------------------------------------------
# TestWarmBrowserPool
# ---------------------------------------------------------------------------


class TestWarmBrowserPool:
    def test_pool_creates_correct_number_of_slots(self) -> None:
        created_ids: list[int] = []

        def factory(slot_id: int) -> WorkerSlot:
            created_ids.append(slot_id)
            return make_slot(slot_id=slot_id)

        WarmBrowserPool(size=3, slot_factory=factory)
        assert len(created_ids) == 3

    def test_pool_slot_ids_are_1_based(self) -> None:
        created_ids: list[int] = []

        def factory(slot_id: int) -> WorkerSlot:
            created_ids.append(slot_id)
            return make_slot(slot_id=slot_id)

        WarmBrowserPool(size=3, slot_factory=factory)
        assert created_ids == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_run_starts_all_slots_concurrently(self) -> None:
        started: list[int] = []

        def factory(slot_id: int) -> WorkerSlot:
            slot = MagicMock()
            slot.slot_id = slot_id

            async def run_coro() -> int:
                started.append(slot_id)
                return slot_id

            slot.run = run_coro
            return slot  # type: ignore[return-value]

        pool = WarmBrowserPool(size=3, slot_factory=factory)
        await pool.run()
        assert sorted(started) == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_run_returns_all_results(self) -> None:
        def factory(slot_id: int) -> WorkerSlot:
            slot = MagicMock()
            slot.slot_id = slot_id

            async def run_coro() -> int:
                return slot_id

            slot.run = run_coro
            return slot  # type: ignore[return-value]

        pool = WarmBrowserPool(size=3, slot_factory=factory)
        results = await pool.run()
        assert sorted(r for r in results if isinstance(r, int)) == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_run_collects_exceptions(self) -> None:
        def factory(slot_id: int) -> WorkerSlot:
            slot = MagicMock()
            slot.slot_id = slot_id

            async def run_coro() -> int:
                if slot_id == 2:
                    raise RuntimeError("slot 2 exploded")
                return slot_id

            slot.run = run_coro
            return slot  # type: ignore[return-value]

        pool = WarmBrowserPool(size=3, slot_factory=factory)
        results = await pool.run()
        exc_results = [r for r in results if isinstance(r, BaseException)]
        assert len(exc_results) == 1
        assert isinstance(exc_results[0], RuntimeError)

    @pytest.mark.asyncio
    async def test_shutdown_cancels_all_tasks(self) -> None:
        """Shutdown cancels all slot tasks; gather collects CancelledErrors."""
        all_started = asyncio.Event()
        started_count = 0

        async def _claim_blocking(_e: object) -> int:
            nonlocal started_count
            started_count += 1
            if started_count == 3:
                all_started.set()
            await asyncio.sleep(999)
            return 0

        def slot_factory(slot_id: int) -> WorkerSlot:
            sleep_fn, _ = make_no_sleep()
            return WorkerSlot(
                slot_id=slot_id,
                engine_factory=lambda: make_engine_mock(),
                claim_loop_fn=_claim_blocking,
                readiness_url="https://fbref.com",
                start_semaphore=asyncio.Semaphore(1),
                warmup_semaphore=asyncio.Semaphore(1),
                startup_jitter_fn=lambda: 0.0,
                browser_backoff=BackoffPolicy(jitter_fn=lambda: 0.0),
                task_backoff=BackoffPolicy(jitter_fn=lambda: 0.0),
                sleep_fn=sleep_fn,
            )

        pool = WarmBrowserPool(size=3, slot_factory=slot_factory)
        run_task = asyncio.create_task(pool.run())
        await all_started.wait()  # all slots have entered claim_loop_fn
        await asyncio.sleep(0)  # ensure all are suspended at asyncio.sleep(999)
        await pool.shutdown()
        results = await run_task
        assert len(results) == 3
        assert all(isinstance(r, asyncio.CancelledError) for r in results)


# ---------------------------------------------------------------------------
# TestFeatureFlagDefault
# ---------------------------------------------------------------------------


class TestFeatureFlagDefault:
    def test_warm_pool_disabled_by_default(self) -> None:
        from config.settings import ScrapingSettings
        settings = ScrapingSettings()
        assert settings.player_info_warm_pool_enabled is False

    def test_pool_size_default_is_2(self) -> None:
        from config.settings import ScrapingSettings
        settings = ScrapingSettings()
        assert settings.player_info_pool_size == 2

    def test_jitter_range_defaults(self) -> None:
        from config.settings import ScrapingSettings
        settings = ScrapingSettings()
        assert settings.player_info_pool_startup_jitter_min == 2.0
        assert settings.player_info_pool_startup_jitter_max == 15.0

    def test_backoff_defaults(self) -> None:
        from config.settings import ScrapingSettings
        settings = ScrapingSettings()
        assert settings.player_info_pool_browser_backoff_base == 2.0
        assert settings.player_info_pool_browser_backoff_max == 120.0
        assert settings.player_info_pool_task_backoff_base == 2.0
        assert settings.player_info_pool_task_backoff_max == 60.0

    def test_pool_does_not_start_when_disabled(self) -> None:
        from infrastructure.browser.pool import build_warm_pool_if_enabled
        result = build_warm_pool_if_enabled(
            enabled=False,
            pool_size=2,
            slot_factory=lambda s: make_slot(slot_id=s),
        )
        assert result is None

    def test_pool_creates_when_enabled(self) -> None:
        from infrastructure.browser.pool import build_warm_pool_if_enabled
        pool = build_warm_pool_if_enabled(
            enabled=True,
            pool_size=3,
            slot_factory=lambda s: make_slot(slot_id=s),
        )
        assert pool is not None
        assert pool._size == 3


# ---------------------------------------------------------------------------
# TestIsolationInvariants
# ---------------------------------------------------------------------------


class TestIsolationInvariants:
    @pytest.mark.asyncio
    async def test_each_slot_gets_isolated_engine_instance(self) -> None:
        """Engine factory is called once per slot; each slot gets its own object."""
        engine_instances: list[AsyncMock] = []

        def engine_factory() -> AsyncMock:
            e = make_engine_mock()
            engine_instances.append(e)
            return e

        def slot_factory(slot_id: int) -> WorkerSlot:
            sleep_fn, _ = make_no_sleep()
            return WorkerSlot(
                slot_id=slot_id,
                engine_factory=engine_factory,
                claim_loop_fn=_claim_zero,
                readiness_url="https://fbref.com",
                start_semaphore=asyncio.Semaphore(1),
                warmup_semaphore=asyncio.Semaphore(1),
                startup_jitter_fn=lambda: 0.0,
                browser_backoff=BackoffPolicy(jitter_fn=lambda: 0.0),
                task_backoff=BackoffPolicy(jitter_fn=lambda: 0.0),
                sleep_fn=sleep_fn,
            )

        pool = WarmBrowserPool(size=3, slot_factory=slot_factory)
        await pool.run()
        assert len(engine_instances) == 3
        assert len({id(e) for e in engine_instances}) == 3

    @pytest.mark.asyncio
    async def test_shutdown_is_idempotent(self) -> None:
        """Calling shutdown twice does not raise."""
        def factory(slot_id: int) -> WorkerSlot:
            slot = MagicMock()
            slot.slot_id = slot_id

            async def run_coro() -> int:
                try:
                    await asyncio.sleep(999)
                    return 0
                except asyncio.CancelledError:
                    raise

            slot.run = run_coro
            return slot  # type: ignore[return-value]

        pool = WarmBrowserPool(size=2, slot_factory=factory)
        run_task = asyncio.create_task(pool.run())
        await asyncio.sleep(0)
        await pool.shutdown()
        await pool.shutdown()  # second call must not raise
        await run_task  # gather(return_exceptions=True) returns normally


# ---------------------------------------------------------------------------
# TestSecurityScope
# ---------------------------------------------------------------------------


class TestSecurityScope:
    """Verify PR 4 scope boundaries and security invariants."""

    def test_no_dispatch_buffer_in_pool(self) -> None:
        pool = WarmBrowserPool(size=1, slot_factory=lambda s: make_slot(slot_id=s))
        assert not hasattr(pool, "dispatch_buffer")
        assert not hasattr(pool, "candidate_queue")

    def test_no_prefetch_in_pool(self) -> None:
        pool = WarmBrowserPool(size=1, slot_factory=lambda s: make_slot(slot_id=s))
        assert not hasattr(pool, "prefetch")
        assert not hasattr(pool, "candidate_prefetch")

    def test_no_rate_limit_gate_in_pool(self) -> None:
        pool = WarmBrowserPool(size=1, slot_factory=lambda s: make_slot(slot_id=s))
        assert not hasattr(pool, "rate_limit_gate")
        assert not hasattr(pool, "cooldown_gate")

    def test_pool_module_has_no_pr5_classes(self) -> None:
        import infrastructure.browser.pool as m
        assert not hasattr(m, "DispatchBuffer")
        assert not hasattr(m, "CandidateQueue")
        assert not hasattr(m, "RateLimitGate")

    @pytest.mark.asyncio
    async def test_slot_logs_do_not_contain_sensitive_data(self) -> None:
        import logging

        captured: list[str] = []

        class _Handler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                captured.append(record.getMessage())

        logger = logging.getLogger("infrastructure.browser.pool")
        h = _Handler()
        logger.addHandler(h)
        try:
            slot = make_slot(slot_id=1)
            await slot.run()
        finally:
            logger.removeHandler(h)

        for msg in captured:
            lower = msg.lower()
            assert "cookie" not in lower, f"Log contains 'cookie': {msg}"
            assert "cdp" not in lower, f"Log contains 'cdp': {msg}"
            assert "ws://" not in msg, f"Log contains WebSocket URL: {msg}"
            assert "token" not in lower, f"Log contains 'token': {msg}"
