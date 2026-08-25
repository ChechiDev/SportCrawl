# tests/unit/cli/test_browser_launcher.py
"""Unit tests for RealBrowserLauncher — strict TDD RED/GREEN cycle.

No real browser, network, DB, Docker, Chrome, Xvfb, CDP, subprocess, or ports.
Coroutine factories use real async def functions (not MagicMock).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from cli.browser_launcher import RealBrowserLauncher
from cli.smoke_clearance_real import (
    CICheckResult,
    ClearanceResult,
    GateStatus,
    HarnessStatus,
    RealClearanceHarness,
    RealClearanceProviders,
    RealClearanceSeams,
    ValidationResult,
)

# ---------------------------------------------------------------------------
# Coroutine factories (real async def — not MagicMock)
# ---------------------------------------------------------------------------


async def _success() -> None:
    """Coroutine that succeeds immediately."""


async def _failure() -> None:
    """Coroutine that raises immediately."""
    raise RuntimeError("probe failed")


def _success_factory() -> Any:
    return _success()


def _failure_factory() -> Any:
    return _failure()


def _make_advancing_clock(values: list[float]) -> Callable[[], float]:
    it = iter(values)

    def _clock() -> float:
        return next(it)

    return _clock


# ---------------------------------------------------------------------------
# TestStart
# ---------------------------------------------------------------------------


class TestStart:
    def test_start_returns_true_when_engine_starter_succeeds(self) -> None:
        launcher = RealBrowserLauncher(
            engine_starter=_success_factory,
            cdp_probe=_success_factory,
        )
        assert launcher.start() is True

    def test_start_returns_false_when_engine_starter_raises(self) -> None:
        launcher = RealBrowserLauncher(
            engine_starter=_failure_factory,
            cdp_probe=_success_factory,
        )
        assert launcher.start() is False

    def test_start_sets_started_state_only_on_success(self) -> None:
        """After a successful start(), wait_cdp_ready() passes the guard and probes."""
        probed = [False]

        async def probe() -> None:
            probed[0] = True

        launcher = RealBrowserLauncher(
            engine_starter=_success_factory,
            cdp_probe=lambda: probe(),
            clock=iter([0.0, 1.0, 2.0]).__next__,
        )
        launcher.start()
        ready, _ = launcher.wait_cdp_ready(timeout_s=10)
        assert ready is True
        assert probed[0] is True

    def test_start_does_not_set_started_state_on_failure(self) -> None:
        """After a failed start(), wait_cdp_ready() hits the guard."""
        launcher = RealBrowserLauncher(
            engine_starter=_failure_factory,
            cdp_probe=_success_factory,
        )
        launcher.start()
        result = launcher.wait_cdp_ready(timeout_s=5)
        assert result == (False, 0)


# ---------------------------------------------------------------------------
# TestWaitCdpReady
# ---------------------------------------------------------------------------


class TestWaitCdpReady:
    def test_wait_cdp_ready_returns_false_if_not_started(self) -> None:
        launcher = RealBrowserLauncher(
            engine_starter=_success_factory,
            cdp_probe=_success_factory,
        )
        # Do NOT call start() — _started is False
        result = launcher.wait_cdp_ready(timeout_s=10)
        assert result == (False, 0)

    def test_wait_cdp_ready_returns_true_and_elapsed_when_probe_succeeds_immediately(
        self,
    ) -> None:
        t = [0.0]

        def clock() -> float:
            v = t[0]
            t[0] += 1.0
            return v

        launcher = RealBrowserLauncher(
            engine_starter=_success_factory,
            cdp_probe=_success_factory,
            clock=clock,
        )
        launcher.start()
        ready, elapsed = launcher.wait_cdp_ready(timeout_s=10)
        assert ready is True
        assert isinstance(elapsed, int)
        assert elapsed >= 0

    def test_wait_cdp_ready_returns_true_after_initial_failures(self) -> None:
        """Probe fails twice, then succeeds on third call."""
        call_count = [0]

        async def flaky_probe() -> None:
            call_count[0] += 1
            if call_count[0] < 3:
                raise RuntimeError("not ready yet")

        t = [0.0]

        def clock() -> float:
            v = t[0]
            t[0] += 1.0
            return v

        def sleeper(_s: float) -> None:
            pass

        launcher = RealBrowserLauncher(
            engine_starter=_success_factory,
            cdp_probe=lambda: flaky_probe(),
            clock=clock,
            sleeper=sleeper,
        )
        launcher.start()
        ready, elapsed = launcher.wait_cdp_ready(timeout_s=30)
        assert ready is True
        assert call_count[0] == 3
        # t0=0.0, loop-check×3=1/2/3, elapsed-read=4.0 → int(4.0-0.0)=4
        assert elapsed == 4

    def test_wait_cdp_ready_calls_sleeper_on_each_failure(self) -> None:
        sleep_calls = [0]

        def sleeper(_s: float) -> None:
            sleep_calls[0] += 1

        call_count = [0]

        async def flaky_probe() -> None:
            call_count[0] += 1
            if call_count[0] < 3:
                raise RuntimeError("not ready")

        t = [0.0]

        def clock() -> float:
            v = t[0]
            t[0] += 1.0
            return v

        launcher = RealBrowserLauncher(
            engine_starter=_success_factory,
            cdp_probe=lambda: flaky_probe(),
            clock=clock,
            sleeper=sleeper,
        )
        launcher.start()
        launcher.wait_cdp_ready(timeout_s=30)
        assert sleep_calls[0] == 2  # sleep on each of the 2 failures

    def test_wait_cdp_ready_returns_false_on_timeout(self) -> None:
        """Loop runs once (probe fails), then clock exceeds deadline."""
        sleep_calls = [0]

        def sleeper(_s: float) -> None:
            sleep_calls[0] += 1

        clock = _make_advancing_clock([0.0, 0.5, 3.0, 3.0])

        launcher = RealBrowserLauncher(
            engine_starter=_success_factory,
            cdp_probe=_failure_factory,
            clock=clock,
            sleeper=sleeper,
        )
        launcher.start()
        ready, elapsed = launcher.wait_cdp_ready(timeout_s=2)
        assert ready is False
        assert elapsed >= 0
        assert sleep_calls[0] == 1

    def test_wait_cdp_ready_elapsed_is_non_negative(self) -> None:
        # t0=0.0, loop-check=1.0, elapsed-read=1.5 → int(1.5-0.0)=1
        clock = _make_advancing_clock([0.0, 1.0, 1.5])
        launcher = RealBrowserLauncher(
            engine_starter=_success_factory,
            cdp_probe=_success_factory,
            clock=clock,
        )
        launcher.start()
        _, elapsed = launcher.wait_cdp_ready(timeout_s=10)
        assert elapsed == 1

    def test_wait_cdp_ready_zero_timeout_returns_false_immediately(self) -> None:
        """timeout_s=0 means deadline == t0, so the loop body never runs."""
        probe_calls = [0]

        async def counting_probe() -> None:
            probe_calls[0] += 1

        clock = _make_advancing_clock([0.0, 0.0, 0.0])
        launcher = RealBrowserLauncher(
            engine_starter=_success_factory,
            cdp_probe=lambda: counting_probe(),
            clock=clock,
        )
        launcher.start()
        result = launcher.wait_cdp_ready(timeout_s=0)
        assert result == (False, 0)
        assert probe_calls[0] == 0


# ---------------------------------------------------------------------------
# Stubs for harness integration tests
# ---------------------------------------------------------------------------


class _BrowserLauncherStub:
    def __init__(
        self, starts: bool = True, cdp_ready: bool = True, cdp_elapsed: int = 2
    ) -> None:
        self._starts = starts
        self._cdp_ready = cdp_ready
        self._cdp_elapsed = cdp_elapsed

    def start(self) -> bool:
        return self._starts

    def wait_cdp_ready(self, timeout_s: int) -> tuple[bool, int]:  # noqa: ARG002
        return self._cdp_ready, self._cdp_elapsed


class _FakeTargetProvider:
    def is_ready(self) -> bool:
        return True

    def source_class(self) -> str:
        return "FAKE_TARGET_CLASS"


class _FakeBrowserParamProvider:
    def is_ready(self) -> bool:
        return True

    def source_class(self) -> str:
        return "FAKE_BROWSER_PARAM_CLASS"

    def validate_against_allowlist(  # noqa: ARG002
        self, allowlist: frozenset[str]
    ) -> bool:
        return True


class _FakeTokenProvider:
    def is_ready(self) -> bool:
        return True

    def source_class(self) -> str:
        return "FAKE_TOKEN_CLASS"


class _FakeCICheck:
    def check_once(self) -> CICheckResult:
        return CICheckResult.ALL_PASS


class _FakeWorkServer:
    def startup(self, timeout_s: int) -> None:  # noqa: ARG002
        pass

    def health_check(self) -> bool:
        return True

    def auth_failure_probe(self) -> int:
        return 401

    def shutdown(self) -> None:
        pass


class _FakeTargetValidator:
    def validate(self, target_class: str) -> ValidationResult:  # noqa: ARG002
        return ValidationResult.VALID


class _FakeClearanceObserver:
    def observe(self, timeout_s: int) -> ClearanceResult:  # noqa: ARG002
        return ClearanceResult(
            obtained=True,
            expires_at=datetime.now(UTC) + timedelta(minutes=2),
            clearance_class="FAKE_CLEARANCE_CLASS",
        )


class _FakeClearancePost:
    def post(self, clearance_class: str) -> tuple[int, int]:  # noqa: ARG002
        return 204, 0


def _make_providers() -> RealClearanceProviders:
    return RealClearanceProviders(
        target=_FakeTargetProvider(),
        browser_params=_FakeBrowserParamProvider(),
        token=_FakeTokenProvider(),
    )


def _make_seams(
    browser_launcher: _BrowserLauncherStub | None = None,
) -> RealClearanceSeams:
    return RealClearanceSeams(
        ci_check=_FakeCICheck(),
        work_server=_FakeWorkServer(),
        target_validator=_FakeTargetValidator(),
        browser_launcher=browser_launcher or _BrowserLauncherStub(),
        clearance_observer=_FakeClearanceObserver(),
        clearance_post=_FakeClearancePost(),
        resolved_host="127.0.0.1",
    )


# ---------------------------------------------------------------------------
# TestHarnessIntegration
# ---------------------------------------------------------------------------


class TestHarnessIntegration:
    def test_harness_gate10_blocks_when_start_returns_false(self) -> None:
        harness = RealClearanceHarness()
        report = harness.run(
            _make_providers(),
            _make_seams(browser_launcher=_BrowserLauncherStub(starts=False)),
        )
        assert report.status == HarnessStatus.BLOCKED
        assert report.error_gate == RealClearanceHarness.GATE_BROWSER_START
        assert (
            report.gate_results[RealClearanceHarness.GATE_BROWSER_START]
            == GateStatus.BLOCKED
        )

    def test_harness_gate11_blocks_when_cdp_not_ready(self) -> None:
        harness = RealClearanceHarness()
        stub = _BrowserLauncherStub(starts=True, cdp_ready=False, cdp_elapsed=31)
        report = harness.run(
            _make_providers(),
            _make_seams(browser_launcher=stub),
        )
        assert report.status == HarnessStatus.BLOCKED
        assert report.error_gate == RealClearanceHarness.GATE_CDP_READY
        gate = RealClearanceHarness.GATE_CDP_READY
        assert report.gate_results[gate] == GateStatus.BLOCKED
