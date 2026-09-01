# tests/unit/cli/test_smoke_clearance_real.py
"""Tests for extension_config_injector seam in RealClearanceHarness.

Strict TDD — RED/GREEN. No real browser, CDP, network, or Docker.
All external interactions injected via fakes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

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
# Minimal fakes (self-contained — no shared helpers from other test modules)
# ---------------------------------------------------------------------------


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


class _FakeBrowserLauncher:
    def __init__(self, starts: bool = True, cdp_ready: bool = True) -> None:
        self._starts = starts
        self._cdp_ready = cdp_ready
        self.stop_called = False

    def start(self) -> bool:
        return self._starts

    def wait_cdp_ready(self, timeout_s: int) -> tuple[bool, int]:  # noqa: ARG002
        return self._cdp_ready, 1

    def stop(self) -> None:
        self.stop_called = True


class _FakeClearanceObserver:
    def __init__(self) -> None:
        self.call_count = 0

    def observe(self, timeout_s: int) -> ClearanceResult:  # noqa: ARG002
        self.call_count += 1
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


def _make_seams(**overrides: object) -> RealClearanceSeams:
    return RealClearanceSeams(
        ci_check=overrides.get("ci_check", _FakeCICheck()),  # type: ignore[arg-type]
        work_server=overrides.get(  # type: ignore[arg-type]
            "work_server", _FakeWorkServer()
        ),
        target_validator=overrides.get(  # type: ignore[arg-type]
            "target_validator", _FakeTargetValidator()
        ),
        browser_launcher=overrides.get(  # type: ignore[arg-type]
            "browser_launcher", _FakeBrowserLauncher()
        ),
        clearance_observer=overrides.get(  # type: ignore[arg-type]
            "clearance_observer", _FakeClearanceObserver()
        ),
        clearance_post=overrides.get(  # type: ignore[arg-type]
            "clearance_post", _FakeClearancePost()
        ),
        resolved_host="127.0.0.1",
    )


# ---------------------------------------------------------------------------
# Tests — extension_config_injector seam
# ---------------------------------------------------------------------------


class TestExtensionConfigInjectorSeam:
    def test_injector_called_after_cdp_gate_and_before_clearance_observation(
        self,
    ) -> None:
        """extension_config_injector is called after CDP ready and before observe()."""
        call_order: list[str] = []

        class _TrackingBrowserLauncher(_FakeBrowserLauncher):
            def wait_cdp_ready(self, timeout_s: int) -> tuple[bool, int]:
                call_order.append("cdp_ready")
                return True, 1

        class _TrackingObserver(_FakeClearanceObserver):
            def observe(self, timeout_s: int) -> ClearanceResult:
                call_order.append("observe")
                return super().observe(timeout_s)

        def injector() -> None:
            call_order.append("injector")

        harness = RealClearanceHarness()
        harness.run(
            _make_providers(),
            _make_seams(
                browser_launcher=_TrackingBrowserLauncher(),
                clearance_observer=_TrackingObserver(),
            ),
            extension_config_injector=injector,
        )

        assert "cdp_ready" in call_order
        assert "injector" in call_order
        assert "observe" in call_order

        cdp_idx = call_order.index("cdp_ready")
        injector_idx = call_order.index("injector")
        observe_idx = call_order.index("observe")

        assert cdp_idx < injector_idx < observe_idx, (
            f"Expected cdp_ready < injector < observe, got order: {call_order}"
        )

    def test_injector_raises_returns_blocked_at_extension_config_inject(
        self,
    ) -> None:
        """When injector raises, harness returns BLOCKED at inject gate."""

        def _raising_injector() -> None:
            raise RuntimeError("CDP storage injection failed")

        harness = RealClearanceHarness()
        report = harness.run(
            _make_providers(),
            _make_seams(),
            extension_config_injector=_raising_injector,
        )

        assert report.status == HarnessStatus.BLOCKED
        assert report.error_gate == "extension_config_inject"
        assert (
            report.gate_results.get("extension_config_inject") == GateStatus.BLOCKED
        )

    def test_injector_raises_clearance_observer_not_called(self) -> None:
        """When injector raises, the clearance observer is never called."""
        observer = _FakeClearanceObserver()

        def _raising_injector() -> None:
            raise ValueError("injection error")

        harness = RealClearanceHarness()
        harness.run(
            _make_providers(),
            _make_seams(clearance_observer=observer),
            extension_config_injector=_raising_injector,
        )

        assert observer.call_count == 0, (
            "observer must not be called when injector raises"
        )

    def test_injector_none_default_skips_gate_and_harness_passes(self) -> None:
        """When extension_config_injector is None (default), gate is skipped."""
        harness = RealClearanceHarness()
        report = harness.run(
            _make_providers(),
            _make_seams(),
            # No extension_config_injector — default None
        )
        assert report.status == HarnessStatus.PASS
        # Gate must NOT appear in gate_results when skipped
        assert "extension_config_inject" not in report.gate_results

    def test_injector_none_explicit_skips_gate_and_harness_passes(self) -> None:
        """Explicitly passing None for extension_config_injector skips the gate."""
        harness = RealClearanceHarness()
        report = harness.run(
            _make_providers(),
            _make_seams(),
            extension_config_injector=None,
        )
        assert report.status == HarnessStatus.PASS
        assert "extension_config_inject" not in report.gate_results

    def test_injector_called_when_provided_and_harness_passes(self) -> None:
        """A non-raising injector results in PASS status."""
        injector_called = [False]

        def _injector() -> None:
            injector_called[0] = True

        harness = RealClearanceHarness()
        report = harness.run(
            _make_providers(),
            _make_seams(),
            extension_config_injector=_injector,
        )

        assert injector_called[0] is True
        assert report.status == HarnessStatus.PASS
        assert report.gate_results.get("extension_config_inject") == GateStatus.PASS

    def test_injector_raises_runtime_error_on_closed_loop_returns_blocked(
        self,
    ) -> None:
        """RuntimeError from injector (closed/running loop guard) returns BLOCKED."""

        def _closed_loop_injector() -> None:
            raise RuntimeError(
                "extension config loop is not usable (closed=True, running=False)"
            )

        harness = RealClearanceHarness()
        report = harness.run(
            _make_providers(),
            _make_seams(),
            extension_config_injector=_closed_loop_injector,
        )

        assert report.status == HarnessStatus.BLOCKED
        assert report.error_gate == "extension_config_inject"
        assert report.gate_results.get("extension_config_inject") == GateStatus.BLOCKED

    def test_gate_11b_logs_error_on_injection_failure(self) -> None:
        """Gate-11b must emit logger.error when injection fails."""
        from unittest.mock import patch

        def _raising_injector() -> None:
            raise ValueError("injection boom")

        harness = RealClearanceHarness()
        with patch("cli.smoke_clearance_real.logger") as mock_logger:
            harness.run(
                _make_providers(),
                _make_seams(),
                extension_config_injector=_raising_injector,
            )
            mock_logger.error.assert_called_once()
            call_args = mock_logger.error.call_args
            # Must log with only the exception type name — no message content
            assert "ValueError" in str(call_args)
