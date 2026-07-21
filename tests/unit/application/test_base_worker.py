"""Unit tests for BaseWorker — outer browser-restart skeleton (Template Method).

TDD cycle: RED written to specify behaviour, GREEN via base_worker.py fixes.
asyncio_mode = "auto" via pyproject.toml — no explicit @pytest.mark.asyncio.

Failure modes under test:
  1. Browser starts successfully → run_claim_loop returns True → worker stops normally.
  2. Browser starts successfully → run_claim_loop returns False → browser restarts.
  3. Browser START raises _MAX_RESTARTS times → worker waits 60s and resets counter,
     then recovers when browser finally starts (does NOT return permanently).
  4. CooldownRequired raised inside run_claim_loop → 30s sleep, then continue.
  5. asyncio.CancelledError propagates through both the inner and outer try/except.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.application.base_worker import BaseWorker, CooldownRequired


# ---------------------------------------------------------------------------
# Concrete test subclass (not mocked ABC — ABCs are tested via concrete impls)
# ---------------------------------------------------------------------------


class _StubWorker(BaseWorker[object]):
    """Minimal concrete BaseWorker that delegates run_claim_loop to an injected callable."""

    def __init__(
        self,
        claim_loop_fn: Any,
        engine_factory: Any = None,
    ) -> None:
        super().__init__(
            worker_id=1,
            session_factory=MagicMock(),
            fetch_gate=asyncio.Semaphore(1),
            profile_base="/tmp/test-profiles",
            worker_labels={},
            worker_counts={},
        )
        self._claim_loop_fn = claim_loop_fn
        self._engine_factory = engine_factory

    @property
    def profile_dir(self) -> str:
        return "/tmp/test-profile-1"

    @property
    def engine_name(self) -> str:
        return "test-engine"

    def _build_engine(self) -> Any:
        if self._engine_factory is not None:
            return self._engine_factory()

        @asynccontextmanager
        async def _ctx() -> Any:
            yield MagicMock()

        return _ctx()

    async def startup_delay(self) -> None:
        return None  # skip random sleep in tests

    async def run_claim_loop(self, engine: Any) -> bool:
        return await self._claim_loop_fn(engine)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _always_stop(_engine: Any) -> bool:
    """Synchronous helper that returns True (stop)."""
    return True


def _always_restart(_engine: Any) -> bool:
    """Synchronous helper that returns False (restart)."""
    return False


def _build_success_engine() -> Any:
    @asynccontextmanager
    async def _ctx() -> Any:
        yield MagicMock()

    return _ctx()


def _build_raising_engine(exc: Exception) -> Any:
    @asynccontextmanager
    async def _ctx() -> Any:
        raise exc
        yield  # unreachable — satisfies async generator protocol

    return _ctx()


# ---------------------------------------------------------------------------
# 1. Happy path: queue empty → worker returns processed count
# ---------------------------------------------------------------------------


class TestBaseWorkerHappyPath:
    async def test_returns_processed_count_when_queue_empty(self) -> None:
        """When run_claim_loop returns True, run() must return self._processed."""
        worker = _StubWorker(claim_loop_fn=AsyncMock(return_value=True))
        result = await worker.run()
        assert result == 0

    async def test_returns_nonzero_when_jobs_processed(self) -> None:
        """Processed count reflects mutations made by run_claim_loop."""

        async def _process_and_stop(engine: Any) -> bool:
            worker._processed = 3
            return True

        worker = _StubWorker(claim_loop_fn=_process_and_stop)
        result = await worker.run()
        assert result == 3


# ---------------------------------------------------------------------------
# 2. run_claim_loop returns False → browser restarts
# ---------------------------------------------------------------------------


class TestBaseWorkerBrowserRestart:
    async def test_run_claim_loop_false_triggers_browser_restart(self) -> None:
        """run_claim_loop returning False must cause the outer loop to start a new engine."""
        call_count = 0

        async def _restart_once_then_stop(engine: Any) -> bool:
            nonlocal call_count
            call_count += 1
            return call_count >= 2  # restart on first call, stop on second

        worker = _StubWorker(claim_loop_fn=_restart_once_then_stop)
        await worker.run()
        assert call_count == 2


# ---------------------------------------------------------------------------
# 3. Browser START failures — must NOT die permanently
# ---------------------------------------------------------------------------


class TestBaseWorkerBrowserStartFailure:
    async def test_worker_does_not_die_after_max_consecutive_failures(self) -> None:
        """After _MAX_RESTARTS consecutive browser-start failures, worker waits
        and resets restart_count rather than returning permanently."""
        _MAX_RESTARTS = 5
        start_call_count = 0

        def _engine_factory() -> Any:
            nonlocal start_call_count
            start_call_count += 1
            # Fail _MAX_RESTARTS times, then succeed once so run_claim_loop can stop it
            if start_call_count <= _MAX_RESTARTS:

                @asynccontextmanager
                async def _fail() -> Any:
                    raise OSError("Chrome failed to start")
                    yield  # unreachable

                return _fail()

            @asynccontextmanager
            async def _ok() -> Any:
                yield MagicMock()

            return _ok()

        worker = _StubWorker(
            claim_loop_fn=AsyncMock(return_value=True),
            engine_factory=_engine_factory,
        )

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = await worker.run()

        assert result == 0, "Worker must complete normally after recovery"
        assert start_call_count == _MAX_RESTARTS + 1, (
            "Worker must retry the engine after the cooldown instead of dying"
        )
        # Verify that the 60s cooldown sleep was called at least once
        sleep_args = [call.args[0] for call in mock_sleep.call_args_list]
        assert 60 in sleep_args, "60-second cooldown must be triggered after max failures"

    async def test_label_updated_during_browser_failure_cooldown(self) -> None:
        """Label must contain Rich markup and 'waiting 60s' during the cooldown."""
        _MAX_RESTARTS = 5
        call_count = 0

        def _engine_factory() -> Any:
            nonlocal call_count
            call_count += 1
            if call_count <= _MAX_RESTARTS:

                @asynccontextmanager
                async def _fail() -> Any:
                    raise OSError("boom")
                    yield

                return _fail()

            @asynccontextmanager
            async def _ok() -> Any:
                yield MagicMock()

            return _ok()

        captured_labels: list[str] = []

        class _CapturingWorker(_StubWorker):
            @property
            def _labels(self) -> dict[int, str]:  # type: ignore[override]
                return self.__labels

            @_labels.setter
            def _labels(self, value: dict[int, str]) -> None:
                self.__labels = value

        worker = _StubWorker(
            claim_loop_fn=AsyncMock(return_value=True),
            engine_factory=_engine_factory,
        )

        original_setter = None

        with patch("asyncio.sleep", new_callable=AsyncMock):
            # Intercept label writes by subclassing the dict assignment post-hoc
            class _TrackingDict(dict):  # type: ignore[type-arg]
                def __setitem__(self, key: Any, value: Any) -> None:
                    captured_labels.append(value)
                    super().__setitem__(key, value)

            worker._labels = _TrackingDict()  # type: ignore[assignment]
            await worker.run()

        cooldown_labels = [l for l in captured_labels if "60s" in l]
        assert cooldown_labels, "A label mentioning '60s' must be set during cooldown"
        assert any("[bold red]" in l for l in cooldown_labels), (
            "Cooldown label must use Rich bold red markup"
        )


# ---------------------------------------------------------------------------
# 4. CooldownRequired → 30s sleep, loop continues
# ---------------------------------------------------------------------------


class TestBaseWorkerCooldownRequired:
    async def test_cooldown_required_sleeps_and_continues(self) -> None:
        """CooldownRequired must trigger a 30s sleep, then re-enter the outer loop."""
        call_count = 0

        async def _raise_then_stop(engine: Any) -> bool:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise CooldownRequired
            return True

        worker = _StubWorker(claim_loop_fn=_raise_then_stop)
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = await worker.run()

        assert result == 0
        assert call_count == 2
        sleep_args = [call.args[0] for call in mock_sleep.call_args_list]
        assert 30 in sleep_args, "30-second cooldown sleep must be triggered"


# ---------------------------------------------------------------------------
# 5. CancelledError propagates
# ---------------------------------------------------------------------------


class TestBaseWorkerCancellation:
    async def test_cancelled_error_propagates_from_inner_loop(self) -> None:
        """asyncio.CancelledError inside run_claim_loop must propagate outward."""

        async def _raise_cancelled(engine: Any) -> bool:
            raise asyncio.CancelledError

        worker = _StubWorker(claim_loop_fn=_raise_cancelled)
        with pytest.raises(asyncio.CancelledError):
            await worker.run()

    async def test_cancelled_error_propagates_from_browser_start(self) -> None:
        """asyncio.CancelledError during browser start must propagate outward."""

        def _engine_factory() -> Any:
            @asynccontextmanager
            async def _ctx() -> Any:
                raise asyncio.CancelledError
                yield

            return _ctx()

        worker = _StubWorker(
            claim_loop_fn=AsyncMock(return_value=True),
            engine_factory=_engine_factory,
        )
        with pytest.raises(asyncio.CancelledError):
            await worker.run()
