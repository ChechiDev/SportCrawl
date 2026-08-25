"""Unit tests for RealClearanceObserver — fully synthetic, no server/browser/cookies."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

from cli.clearance_observer import POLL_INTERVAL_SECONDS, RealClearanceObserver
from cli.smoke_clearance_real import (
    ClearanceResult,
    GateStatus,
    HarnessStatus,
    RealClearanceHarness,
    RealClearanceProviders,
    RealClearanceSeams,
    scan_for_sensitive,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_advancing_clock(values: list[float]) -> Any:
    it = iter(values)
    return lambda: next(it)


def _label() -> str:
    return "cf_clearance@fbref.com"


def _success(
    expires_at: datetime | None = None,
    clearance_class: str = "",
) -> ClearanceResult:
    return ClearanceResult(
        obtained=True,
        expires_at=expires_at or (datetime.now(UTC) + timedelta(minutes=2)),
        clearance_class=clearance_class or _label(),
    )


def _make_observer(
    *,
    clearance_getter: Any,
    clock: Any = None,
    sleeper: Any = None,
) -> RealClearanceObserver:
    kwargs: dict[str, Any] = {"clearance_getter": clearance_getter}
    if clock is not None:
        kwargs["clock"] = clock
    if sleeper is not None:
        kwargs["sleeper"] = sleeper
    return RealClearanceObserver(**kwargs)


# ---------------------------------------------------------------------------
# observe — timeout path
# ---------------------------------------------------------------------------


class TestObserveTimeout:
    def test_getter_always_none_returns_obtained_false(self) -> None:
        def _past_deadline() -> float:
            return float("inf")

        getter = MagicMock(return_value=None)
        obs = _make_observer(
            clearance_getter=getter,
            clock=_past_deadline,
            sleeper=MagicMock(),
        )
        result = obs.observe(timeout_s=0)
        assert result.obtained is False

    def test_timeout_s_zero_returns_immediately_without_calling_getter(self) -> None:
        getter = MagicMock(return_value=_success())
        obs = _make_observer(
            clearance_getter=getter,
            clock=_make_advancing_clock([0.0, 0.0]),
            sleeper=MagicMock(),
        )
        result = obs.observe(timeout_s=0)
        getter.assert_not_called()
        assert result.obtained is False

    def test_timeout_result_has_none_expires_at_and_empty_class(self) -> None:
        obs = _make_observer(
            clearance_getter=MagicMock(return_value=None),
            clock=lambda: float("inf"),
            sleeper=MagicMock(),
        )
        result = obs.observe(timeout_s=0)
        assert result.expires_at is None
        assert result.clearance_class == ""


# ---------------------------------------------------------------------------
# observe — success path
# ---------------------------------------------------------------------------


class TestObserveSuccess:
    def test_getter_returns_success_on_first_call(self) -> None:
        expected = _success()
        getter = MagicMock(return_value=expected)
        obs = _make_observer(
            clearance_getter=getter,
            clock=_make_advancing_clock([0.0, 0.5]),
            sleeper=MagicMock(),
        )
        result = obs.observe(timeout_s=10)
        assert result is expected
        assert result.obtained is True

    def test_success_result_returned_unchanged(self) -> None:
        exp_at = datetime.now(UTC) + timedelta(minutes=3)
        expected = ClearanceResult(
            obtained=True, expires_at=exp_at, clearance_class="cf_clearance@fbref.com"
        )
        getter = MagicMock(return_value=expected)
        obs = _make_observer(
            clearance_getter=getter,
            clock=_make_advancing_clock([0.0, 0.1]),
            sleeper=MagicMock(),
        )
        result = obs.observe(timeout_s=10)
        assert result.obtained is True
        assert result.expires_at is exp_at
        assert result.clearance_class == "cf_clearance@fbref.com"

    def test_expires_at_passes_through_from_getter(self) -> None:
        exp_at = datetime.now(UTC) + timedelta(seconds=90)
        getter = MagicMock(return_value=ClearanceResult(
            obtained=True, expires_at=exp_at, clearance_class=_label()
        ))
        obs = _make_observer(
            clearance_getter=getter,
            clock=_make_advancing_clock([0.0, 0.2]),
            sleeper=MagicMock(),
        )
        result = obs.observe(timeout_s=10)
        assert result.expires_at is exp_at

    def test_getter_none_twice_then_success_sleeper_called_twice(self) -> None:
        call_count = 0

        def _getter() -> ClearanceResult | None:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return None
            return _success()

        mock_sleeper = MagicMock()
        obs = _make_observer(
            clearance_getter=_getter,
            clock=_make_advancing_clock([0.0, 0.5, 1.0, 1.5, 2.0]),
            sleeper=mock_sleeper,
        )
        result = obs.observe(timeout_s=10)
        assert result.obtained is True
        assert mock_sleeper.call_count == 2

    def test_sleeper_called_with_poll_interval(self) -> None:
        call_count = 0

        def _getter() -> ClearanceResult | None:
            nonlocal call_count
            call_count += 1
            return _success() if call_count >= 2 else None

        mock_sleeper = MagicMock()
        obs = _make_observer(
            clearance_getter=_getter,
            clock=_make_advancing_clock([0.0, 0.5, 1.0, 1.5]),
            sleeper=mock_sleeper,
        )
        obs.observe(timeout_s=10)
        mock_sleeper.assert_called_with(POLL_INTERVAL_SECONDS)


# ---------------------------------------------------------------------------
# observe — obtained=False treatment
# ---------------------------------------------------------------------------


class TestObserveFalseResult:
    def test_obtained_false_from_getter_treated_as_miss(self) -> None:
        call_count = 0

        def _getter() -> ClearanceResult | None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return ClearanceResult(
                    obtained=False, expires_at=None, clearance_class=""
                )
            return _success()

        mock_sleeper = MagicMock()
        obs = _make_observer(
            clearance_getter=_getter,
            clock=_make_advancing_clock([0.0, 0.5, 1.0, 1.5]),
            sleeper=mock_sleeper,
        )
        result = obs.observe(timeout_s=10)
        assert result.obtained is True
        assert mock_sleeper.call_count == 1


# ---------------------------------------------------------------------------
# Secret safety
# ---------------------------------------------------------------------------


class TestSecretSafety:
    def test_clearance_class_label_passes_scan_for_sensitive(self) -> None:
        getter = MagicMock(return_value=_success(clearance_class=_label()))
        obs = _make_observer(
            clearance_getter=getter,
            clock=_make_advancing_clock([0.0, 0.5]),
            sleeper=MagicMock(),
        )
        result = obs.observe(timeout_s=10)
        assert not scan_for_sensitive(result.clearance_class)

    def test_timeout_clearance_class_passes_scan_for_sensitive(self) -> None:
        obs = _make_observer(
            clearance_getter=MagicMock(return_value=None),
            clock=lambda: float("inf"),
            sleeper=MagicMock(),
        )
        result = obs.observe(timeout_s=0)
        assert not scan_for_sensitive(result.clearance_class)


# ---------------------------------------------------------------------------
# Harness integration stubs
# ---------------------------------------------------------------------------


class _FakeTargetProvider:
    def is_ready(self) -> bool:
        return True

    def source_class(self) -> str:
        return "FAKE_TARGET"


class _FakeBrowserParamProvider:
    def is_ready(self) -> bool:
        return True

    def source_class(self) -> str:
        return "FAKE_BROWSER_PARAM"

    def validate_against_allowlist(  # noqa: ARG002
        self, _allowlist: frozenset[str]
    ) -> bool:
        return True


class _FakeTokenProvider:
    def is_ready(self) -> bool:
        return True

    def source_class(self) -> str:
        return "FAKE_TOKEN"


class _FakeCICheck:
    def check_once(self) -> Any:
        from cli.smoke_clearance_real import CICheckResult

        return CICheckResult.ALL_PASS


class _FakeTargetValidator:
    def validate(self, _target_class: str) -> Any:  # noqa: ARG002
        from cli.smoke_clearance_real import ValidationResult

        return ValidationResult.VALID


class _FakeWorkServer:
    def startup(self, timeout_s: int) -> None:  # noqa: ARG002
        pass

    def health_check(self) -> bool:
        return True

    def auth_failure_probe(self) -> int:
        return 401

    def shutdown(self) -> None:
        pass


class _FakeBrowserLauncher:
    def start(self) -> bool:
        return True

    def wait_cdp_ready(self, timeout_s: int) -> tuple[bool, int]:  # noqa: ARG002
        return True, 1


class _FakeClearancePost:
    def post(self, _clearance_class: str) -> tuple[int, int]:  # noqa: ARG002
        return 204, 0


def _make_providers() -> RealClearanceProviders:
    return RealClearanceProviders(
        target=_FakeTargetProvider(),  # type: ignore[arg-type]
        browser_params=_FakeBrowserParamProvider(),  # type: ignore[arg-type]
        token=_FakeTokenProvider(),  # type: ignore[arg-type]
    )


def _make_seams(observer: Any) -> RealClearanceSeams:
    return RealClearanceSeams(
        ci_check=_FakeCICheck(),  # type: ignore[arg-type]
        work_server=_FakeWorkServer(),  # type: ignore[arg-type]
        target_validator=_FakeTargetValidator(),  # type: ignore[arg-type]
        browser_launcher=_FakeBrowserLauncher(),  # type: ignore[arg-type]
        clearance_observer=observer,  # type: ignore[arg-type]
        clearance_post=_FakeClearancePost(),  # type: ignore[arg-type]
        resolved_host="127.0.0.1",
    )


# ---------------------------------------------------------------------------
# Harness integration — gates 12 and 13
# ---------------------------------------------------------------------------


class TestHarnessClearanceObserverGates:
    def test_harness_gate12_blocks_when_observer_returns_obtained_false(
        self,
    ) -> None:
        obs = _make_observer(
            clearance_getter=MagicMock(return_value=None),
            clock=lambda: float("inf"),
            sleeper=MagicMock(),
        )
        report = RealClearanceHarness().run(_make_providers(), _make_seams(obs))
        gate = RealClearanceHarness.GATE_CLEARANCE_OBSERVED
        assert report.gate_results.get(gate) == GateStatus.BLOCKED
        assert report.status == HarnessStatus.BLOCKED
        assert report.error_gate == gate

    def test_harness_gate13_blocks_when_expires_at_is_expired(self) -> None:
        past = datetime.now(UTC) - timedelta(minutes=1)
        obs = _make_observer(
            clearance_getter=MagicMock(
                return_value=ClearanceResult(
                    obtained=True,
                    expires_at=past,
                    clearance_class=_label(),
                )
            ),
            clock=_make_advancing_clock([0.0, 0.5]),
            sleeper=MagicMock(),
        )
        report = RealClearanceHarness().run(_make_providers(), _make_seams(obs))
        gate = RealClearanceHarness.GATE_EXPIRES_AT
        assert report.gate_results.get(gate) == GateStatus.BLOCKED
        assert report.status == HarnessStatus.BLOCKED
        assert report.error_gate == gate

    def test_harness_gate13_blocks_when_expires_at_is_too_far_in_future(
        self,
    ) -> None:
        far_future = datetime.now(UTC) + timedelta(hours=2)
        obs = _make_observer(
            clearance_getter=MagicMock(
                return_value=ClearanceResult(
                    obtained=True,
                    expires_at=far_future,
                    clearance_class=_label(),
                )
            ),
            clock=_make_advancing_clock([0.0, 0.5]),
            sleeper=MagicMock(),
        )
        report = RealClearanceHarness().run(_make_providers(), _make_seams(obs))
        gate = RealClearanceHarness.GATE_EXPIRES_AT
        assert report.gate_results.get(gate) == GateStatus.BLOCKED
        assert report.status == HarnessStatus.BLOCKED
        assert report.error_gate == gate
