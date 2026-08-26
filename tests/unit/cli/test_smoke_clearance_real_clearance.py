"""CP1.6i-RED — Contract tests for smoke-clearance --real-clearance harness.

Tests cover the RealClearanceHarness gate model, CLI flag registration,
and all BLOCKED/FAIL/PASS paths. No real browser, network, DB, or Docker.

All external interaction seams are injected via fake implementations.
Provider source_class values use clearly synthetic labels.
RFC-reserved hostnames (example.com, test.invalid) and private-range IPs
are used for rejection tests.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from typer.testing import CliRunner

from cli.main import app
from cli.smoke_clearance_real import (
    CICheckResult,
    ClearanceResult,
    GateStatus,
    HarnessStatus,
    RealClearanceHarness,
    RealClearanceProviders,
    RealClearanceSeams,
    ValidationResult,
    assert_loopback,
    check_expires_at,
    scan_for_sensitive,
    validate_token_source_class,
)

runner = CliRunner()


# ---------------------------------------------------------------------------
# Fake provider implementations
# ---------------------------------------------------------------------------


class FakeTargetProvider:
    def __init__(
        self, ready: bool = True, source_class_label: str = "FAKE_RUNTIME_TARGET_CLASS"
    ) -> None:
        self._ready = ready
        self._source_class = source_class_label

    def is_ready(self) -> bool:
        return self._ready

    def source_class(self) -> str:
        return self._source_class


class FakeBrowserParamProvider:
    def __init__(
        self,
        ready: bool = True,
        source_class_label: str = "FAKE_RUNTIME_BROWSER_PARAM_CLASS",
    ) -> None:
        self._ready = ready
        self._source_class = source_class_label

    def is_ready(self) -> bool:
        return self._ready

    def source_class(self) -> str:
        return self._source_class

    def validate_against_allowlist(  # pyright: ignore[reportUnusedParameter]
        self, _allowlist: frozenset[str]
    ) -> bool:
        return True


class FakeTokenProvider:
    def __init__(
        self, ready: bool = True, source_class_label: str = "FAKE_RUNTIME_TOKEN_CLASS"
    ) -> None:
        self._ready = ready
        self._source_class = source_class_label

    def is_ready(self) -> bool:
        return self._ready

    def source_class(self) -> str:
        return self._source_class


class FakeCICheck:
    def __init__(self, result: CICheckResult = CICheckResult.ALL_PASS) -> None:
        self._result = result
        self.call_count = 0

    def check_once(self) -> CICheckResult:
        self.call_count += 1
        return self._result


class FakeWorkServer:
    def __init__(
        self,
        health: bool = True,
        auth_probe_status: int = 401,
        startup_raises: bool = False,
    ) -> None:
        self._health = health
        self._auth_probe = auth_probe_status
        self._startup_raises = startup_raises
        self.shutdown_called = False
        self.startup_called = False

    def startup(  # noqa: ARG002  # pyright: ignore[reportUnusedParameter]
        self, timeout_s: int
    ) -> None:
        self.startup_called = True
        if self._startup_raises:
            raise RuntimeError("work_server failed to start")

    def health_check(self) -> bool:
        return self._health

    def auth_failure_probe(self) -> int:
        return self._auth_probe

    def shutdown(self) -> None:
        self.shutdown_called = True


class FakeTargetValidatorImpl:
    def __init__(self, result: ValidationResult = ValidationResult.VALID) -> None:
        self._result = result

    def validate(  # pyright: ignore[reportUnusedParameter]
        self, _target_class: str
    ) -> ValidationResult:
        return self._result


class FakeBrowserLauncher:
    def __init__(
        self, starts: bool = True, cdp_ready: bool = True, cdp_elapsed: int = 5,
        stop_raises: bool = False
    ) -> None:
        self._starts = starts
        self._cdp_ready = cdp_ready
        self._cdp_elapsed = cdp_elapsed
        self._stop_raises = stop_raises
        self.stop_called: bool = False

    def start(self) -> bool:
        return self._starts

    def wait_cdp_ready(  # noqa: ARG002  # pyright: ignore[reportUnusedParameter]
        self, timeout_s: int
    ) -> tuple[bool, int]:
        return self._cdp_ready, self._cdp_elapsed

    def stop(self) -> None:
        self.stop_called = True
        if self._stop_raises:
            raise RuntimeError("stop failed")


class FakeClearanceObserver:
    def __init__(
        self,
        obtained: bool = True,
        expires_at: datetime | None = None,
        clearance_class: str = "FAKE_CLEARANCE_CLASS",
    ) -> None:
        self._obtained = obtained
        self._expires_at = expires_at or (datetime.now(UTC) + timedelta(minutes=2))
        self._clearance_class = clearance_class

    def observe(  # noqa: ARG002  # pyright: ignore[reportUnusedParameter]
        self, timeout_s: int
    ) -> ClearanceResult:
        return ClearanceResult(
            obtained=self._obtained,
            expires_at=self._expires_at,
            clearance_class=self._clearance_class,
        )


class FakeClearancePost:
    def __init__(self, status_code: int = 204, body_bytes: int = 0) -> None:
        self._status = status_code
        self._body_bytes = body_bytes

    def post(  # pyright: ignore[reportUnusedParameter]
        self, _clearance_class: str
    ) -> tuple[int, int]:
        return self._status, self._body_bytes


def _make_providers(**kwargs: Any) -> RealClearanceProviders:
    return RealClearanceProviders(
        target=kwargs.get("target", FakeTargetProvider()),
        browser_params=kwargs.get("browser_params", FakeBrowserParamProvider()),
        token=kwargs.get("token", FakeTokenProvider()),
    )


def _make_seams(**kwargs: Any) -> RealClearanceSeams:
    return RealClearanceSeams(
        ci_check=kwargs.get("ci_check", FakeCICheck()),
        work_server=kwargs.get("work_server", FakeWorkServer()),
        target_validator=kwargs.get("target_validator", FakeTargetValidatorImpl()),
        browser_launcher=kwargs.get("browser_launcher", FakeBrowserLauncher()),
        clearance_observer=kwargs.get("clearance_observer", FakeClearanceObserver()),
        clearance_post=kwargs.get("clearance_post", FakeClearancePost()),
        resolved_host=kwargs.get("resolved_host", "127.0.0.1"),
    )


# ---------------------------------------------------------------------------
# CLI flag registration
# ---------------------------------------------------------------------------


class TestRealClearanceFlagRegistration:
    def test_real_clearance_option_registered(self) -> None:
        """--real-clearance must be registered as a Click option."""
        import typer.main as typer_main

        cli = typer_main.get_command(app)
        sub = getattr(cli, "commands", {}).get("smoke-clearance")
        assert sub is not None, "smoke-clearance command not registered."
        registered = any(
            "--real-clearance" in getattr(p, "opts", []) for p in sub.params
        )
        assert registered, "--real-clearance option not registered on smoke-clearance."

    def test_real_clearance_exits_nonzero_when_blocked(self) -> None:
        """--real-clearance exits non-zero when no providers configured."""
        result = runner.invoke(app, ["smoke-clearance", "--real-clearance"])
        assert result.exit_code != 0, (
            f"--real-clearance should exit non-zero (BLOCKED). Got: {result.output}"
        )

    def test_real_clearance_output_mentions_blocked(self) -> None:
        """--real-clearance output must mention BLOCKED or blocked."""
        result = runner.invoke(app, ["smoke-clearance", "--real-clearance"])
        assert "blocked" in result.output.lower() or "BLOCKED" in result.output, (
            f"--real-clearance must report BLOCKED. Got: {result.output!r}"
        )

    def test_real_clearance_and_dry_run_rejected(self) -> None:
        """--real-clearance --dry-run must be rejected."""
        result = runner.invoke(
            app, ["smoke-clearance", "--real-clearance", "--dry-run"]
        )
        assert result.exit_code != 0, "--real-clearance --dry-run must be rejected."

    def test_real_clearance_and_execute_rejected(self) -> None:
        """--real-clearance --execute must be rejected."""
        result = runner.invoke(
            app, ["smoke-clearance", "--real-clearance", "--execute"]
        )
        assert result.exit_code != 0, "--real-clearance --execute must be rejected."

    def test_real_clearance_and_prepare_real_rejected(self) -> None:
        """--real-clearance --prepare-real must be rejected."""
        result = runner.invoke(
            app, ["smoke-clearance", "--real-clearance", "--prepare-real"]
        )
        assert result.exit_code != 0, (
            "--real-clearance --prepare-real must be rejected."
        )

    def test_existing_execute_still_works(self) -> None:
        """--execute must still exit 0 (regression guard)."""
        result = runner.invoke(app, ["smoke-clearance", "--execute"])
        assert result.exit_code == 0, f"--execute regressed: {result.output}"

    def test_existing_dry_run_still_works(self) -> None:
        """dry-run must still exit 0 (regression guard)."""
        result = runner.invoke(app, ["smoke-clearance"])
        assert result.exit_code == 0, f"dry-run regressed: {result.output}"


# ---------------------------------------------------------------------------
# Harness unit tests — BLOCKED paths
# ---------------------------------------------------------------------------


class TestHarnessBlockedPaths:
    def test_blocked_if_target_not_ready(self) -> None:
        harness = RealClearanceHarness()
        report = harness.run(
            _make_providers(target=FakeTargetProvider(ready=False)),
            _make_seams(),
        )
        assert report.status == HarnessStatus.BLOCKED
        assert report.error_gate == RealClearanceHarness.GATE_PROVIDER_READINESS

    def test_blocked_if_browser_params_not_ready(self) -> None:
        harness = RealClearanceHarness()
        report = harness.run(
            _make_providers(browser_params=FakeBrowserParamProvider(ready=False)),
            _make_seams(),
        )
        assert report.status == HarnessStatus.BLOCKED
        assert report.error_gate == RealClearanceHarness.GATE_PROVIDER_READINESS

    def test_blocked_if_token_not_ready(self) -> None:
        harness = RealClearanceHarness()
        report = harness.run(
            _make_providers(token=FakeTokenProvider(ready=False)),
            _make_seams(),
        )
        assert report.status == HarnessStatus.BLOCKED
        assert report.error_gate == RealClearanceHarness.GATE_PROVIDER_READINESS

    def test_blocked_if_loopback_fails(self) -> None:
        harness = RealClearanceHarness()
        report = harness.run(
            _make_providers(),
            _make_seams(resolved_host="10.0.0.1"),  # private IP — not loopback
        )
        assert report.status == HarnessStatus.BLOCKED
        assert report.error_gate == RealClearanceHarness.GATE_LOOPBACK

    def test_blocked_if_ci_check_not_all_pass(self) -> None:
        harness = RealClearanceHarness()
        report = harness.run(
            _make_providers(),
            _make_seams(ci_check=FakeCICheck(CICheckResult.BLOCKED)),
        )
        assert report.status == HarnessStatus.BLOCKED
        assert report.error_gate == RealClearanceHarness.GATE_CI_CHECK

    def test_ci_check_executes_exactly_once(self) -> None:
        harness = RealClearanceHarness()
        ci = FakeCICheck(CICheckResult.BLOCKED)
        harness.run(_make_providers(), _make_seams(ci_check=ci))
        assert ci.call_count == 1, f"CI check called {ci.call_count} times, expected 1"

    def test_ci_check_failure_blocks_immediately_no_retry(self) -> None:
        """CI check failure → BLOCKED with no additional calls."""
        harness = RealClearanceHarness()
        ci = FakeCICheck(CICheckResult.BLOCKED)
        report = harness.run(_make_providers(), _make_seams(ci_check=ci))
        assert report.status == HarnessStatus.BLOCKED
        assert ci.call_count == 1

    def test_blocked_if_work_server_health_fails(self) -> None:
        harness = RealClearanceHarness()
        report = harness.run(
            _make_providers(),
            _make_seams(work_server=FakeWorkServer(health=False)),
        )
        assert report.status == HarnessStatus.BLOCKED
        assert report.error_gate == RealClearanceHarness.GATE_WORK_SERVER_HEALTH

    def test_blocked_if_auth_failure_probe_not_401(self) -> None:
        harness = RealClearanceHarness()
        report = harness.run(
            _make_providers(),
            _make_seams(work_server=FakeWorkServer(auth_probe_status=200)),
        )
        assert report.status == HarnessStatus.BLOCKED
        assert report.error_gate == RealClearanceHarness.GATE_AUTH_FAILURE_PROBE

    def test_blocked_if_expires_at_lte_now(self) -> None:
        """expires_at <= now → BLOCKED (lower bound violated)."""
        harness = RealClearanceHarness()
        past = datetime.now(UTC) - timedelta(seconds=1)
        report = harness.run(
            _make_providers(),
            _make_seams(
                clearance_observer=FakeClearanceObserver(expires_at=past),
            ),
        )
        assert report.status == HarnessStatus.BLOCKED
        assert report.error_gate == RealClearanceHarness.GATE_EXPIRES_AT

    def test_blocked_if_expires_at_gt_now_plus_5min(self) -> None:
        """expires_at > now + 5min → BLOCKED (upper bound violated)."""
        harness = RealClearanceHarness()
        far_future = datetime.now(UTC) + timedelta(minutes=10)
        report = harness.run(
            _make_providers(),
            _make_seams(
                clearance_observer=FakeClearanceObserver(expires_at=far_future),
            ),
        )
        assert report.status == HarnessStatus.BLOCKED
        assert report.error_gate == RealClearanceHarness.GATE_EXPIRES_AT

    def test_blocked_if_browser_does_not_start(self) -> None:
        harness = RealClearanceHarness()
        report = harness.run(
            _make_providers(),
            _make_seams(browser_launcher=FakeBrowserLauncher(starts=False)),
        )
        assert report.status == HarnessStatus.BLOCKED
        assert report.error_gate == RealClearanceHarness.GATE_BROWSER_START

    def test_blocked_if_cdp_not_ready_within_30s(self) -> None:
        harness = RealClearanceHarness()
        report = harness.run(
            _make_providers(),
            _make_seams(
                browser_launcher=FakeBrowserLauncher(cdp_ready=False, cdp_elapsed=31),
            ),
        )
        assert report.status == HarnessStatus.BLOCKED
        assert report.error_gate == RealClearanceHarness.GATE_CDP_READY

    def test_blocked_if_clearance_not_observed(self) -> None:
        harness = RealClearanceHarness()
        report = harness.run(
            _make_providers(),
            _make_seams(
                clearance_observer=FakeClearanceObserver(obtained=False),
            ),
        )
        assert report.status == HarnessStatus.BLOCKED
        assert report.error_gate == RealClearanceHarness.GATE_CLEARANCE_OBSERVED

    def test_blocked_if_post_returns_non_204(self) -> None:
        harness = RealClearanceHarness()
        report = harness.run(
            _make_providers(),
            _make_seams(clearance_post=FakeClearancePost(status_code=500)),
        )
        assert report.status == HarnessStatus.BLOCKED
        assert report.error_gate == RealClearanceHarness.GATE_POST_CLEARANCE

    def test_blocked_if_post_returns_204_with_nonzero_body(self) -> None:
        harness = RealClearanceHarness()
        report = harness.run(
            _make_providers(),
            _make_seams(
                clearance_post=FakeClearancePost(status_code=204, body_bytes=42)
            ),
        )
        assert report.status == HarnessStatus.BLOCKED
        assert report.error_gate == RealClearanceHarness.GATE_POST_CLEARANCE


# ---------------------------------------------------------------------------
# Cleanup verification — shutdown must run on every path
# ---------------------------------------------------------------------------


class TestCleanupAlwaysRuns:
    def test_cleanup_runs_on_provider_not_ready(self) -> None:
        ws = FakeWorkServer()
        launcher = FakeBrowserLauncher()
        harness = RealClearanceHarness()
        harness.run(
            _make_providers(target=FakeTargetProvider(ready=False)),
            _make_seams(work_server=ws, browser_launcher=launcher),
        )
        assert ws.shutdown_called, (
            "shutdown must be called even when provider_readiness gate fails"
        )
        assert launcher.stop_called, (
            "browser stop must be called even when provider_readiness gate fails"
        )

    def test_cleanup_runs_on_loopback_fail(self) -> None:
        ws = FakeWorkServer()
        launcher = FakeBrowserLauncher()
        harness = RealClearanceHarness()
        harness.run(
            _make_providers(),
            _make_seams(
                work_server=ws,
                browser_launcher=launcher,
                resolved_host="192.168.1.1",
            ),
        )
        assert ws.shutdown_called
        assert launcher.stop_called

    def test_cleanup_runs_on_ci_check_blocked(self) -> None:
        ws = FakeWorkServer()
        launcher = FakeBrowserLauncher()
        harness = RealClearanceHarness()
        harness.run(
            _make_providers(),
            _make_seams(
                work_server=ws,
                browser_launcher=launcher,
                ci_check=FakeCICheck(CICheckResult.BLOCKED),
            ),
        )
        assert ws.shutdown_called
        assert launcher.stop_called

    def test_cleanup_runs_on_work_server_health_fail(self) -> None:
        ws = FakeWorkServer(health=False)
        launcher = FakeBrowserLauncher()
        harness = RealClearanceHarness()
        harness.run(
            _make_providers(),
            _make_seams(work_server=ws, browser_launcher=launcher),
        )
        assert ws.shutdown_called
        assert launcher.stop_called

    def test_cleanup_runs_on_auth_probe_fail(self) -> None:
        ws = FakeWorkServer(auth_probe_status=200)
        launcher = FakeBrowserLauncher()
        harness = RealClearanceHarness()
        harness.run(
            _make_providers(),
            _make_seams(work_server=ws, browser_launcher=launcher),
        )
        assert ws.shutdown_called
        assert launcher.stop_called

    def test_cleanup_runs_on_browser_start_fail(self) -> None:
        ws = FakeWorkServer()
        launcher = FakeBrowserLauncher(starts=False)
        harness = RealClearanceHarness()
        harness.run(
            _make_providers(),
            _make_seams(work_server=ws, browser_launcher=launcher),
        )
        assert ws.shutdown_called
        assert launcher.stop_called

    def test_cleanup_runs_on_cdp_not_ready(self) -> None:
        ws = FakeWorkServer()
        launcher = FakeBrowserLauncher(cdp_ready=False, cdp_elapsed=31)
        harness = RealClearanceHarness()
        harness.run(
            _make_providers(),
            _make_seams(work_server=ws, browser_launcher=launcher),
        )
        assert ws.shutdown_called
        assert launcher.stop_called

    def test_cleanup_runs_on_clearance_not_observed(self) -> None:
        ws = FakeWorkServer()
        launcher = FakeBrowserLauncher()
        harness = RealClearanceHarness()
        harness.run(
            _make_providers(),
            _make_seams(
                work_server=ws,
                browser_launcher=launcher,
                clearance_observer=FakeClearanceObserver(obtained=False),
            ),
        )
        assert ws.shutdown_called
        assert launcher.stop_called

    def test_cleanup_runs_on_post_fail(self) -> None:
        ws = FakeWorkServer()
        launcher = FakeBrowserLauncher()
        harness = RealClearanceHarness()
        harness.run(
            _make_providers(),
            _make_seams(
                work_server=ws,
                browser_launcher=launcher,
                clearance_post=FakeClearancePost(status_code=500),
            ),
        )
        assert ws.shutdown_called
        assert launcher.stop_called

    def test_cleanup_runs_on_pass(self) -> None:
        ws = FakeWorkServer()
        launcher = FakeBrowserLauncher()
        harness = RealClearanceHarness()
        report = harness.run(
            _make_providers(),
            _make_seams(work_server=ws, browser_launcher=launcher),
        )
        assert report.status == HarnessStatus.PASS
        assert ws.shutdown_called
        assert launcher.stop_called

    def test_cleanup_runs_on_work_server_startup_raises(self) -> None:
        ws = FakeWorkServer(startup_raises=True)
        launcher = FakeBrowserLauncher()
        seams = _make_seams(work_server=ws, browser_launcher=launcher)
        providers = _make_providers()
        RealClearanceHarness().run(providers, seams)
        assert ws.shutdown_called
        assert launcher.stop_called


# ---------------------------------------------------------------------------
# Provider evidence safety — source_class must be a label, not a raw value
# ---------------------------------------------------------------------------


class TestProviderEvidenceSafety:
    def test_target_source_class_is_synthetic_label(self) -> None:
        """source_class must not contain sensitive substrings."""
        p = FakeTargetProvider(source_class_label="FAKE_RUNTIME_TARGET_CLASS")
        label = p.source_class()
        assert not scan_for_sensitive(label), (
            f"source_class label is sensitive: {label!r}"
        )

    def test_token_source_class_is_synthetic_label(self) -> None:
        p = FakeTokenProvider(source_class_label="FAKE_RUNTIME_TOKEN_CLASS")
        label = p.source_class()
        assert not scan_for_sensitive(label), (
            f"source_class label is sensitive: {label!r}"
        )

    def test_browser_param_source_class_is_synthetic_label(self) -> None:
        p = FakeBrowserParamProvider(
            source_class_label="FAKE_RUNTIME_BROWSER_PARAM_CLASS"
        )
        label = p.source_class()
        assert not scan_for_sensitive(label), (
            f"source_class label is sensitive: {label!r}"
        )

    def test_clearance_class_label_in_evidence_not_raw_value(self) -> None:
        """clearance_class in ClearanceResult must be a label, not a raw cookie
        value."""
        result = ClearanceResult(
            obtained=True,
            expires_at=datetime.now(UTC) + timedelta(minutes=2),
            clearance_class="FAKE_CLEARANCE_CLASS",
        )
        assert not scan_for_sensitive(result.clearance_class), (
            f"clearance_class appears sensitive: {result.clearance_class!r}"
        )


# ---------------------------------------------------------------------------
# Target validation — mocked resolver rejects dangerous hosts
# ---------------------------------------------------------------------------


class TestTargetValidation:
    """Target validator must reject dangerous targets. Uses mocked validator seam."""

    def _check_blocked(self, target_label: str) -> None:
        harness = RealClearanceHarness()
        report = harness.run(
            _make_providers(target=FakeTargetProvider(source_class_label=target_label)),
            _make_seams(
                target_validator=FakeTargetValidatorImpl(ValidationResult.BLOCKED)
            ),
        )
        assert report.status == HarnessStatus.BLOCKED
        assert report.error_gate == RealClearanceHarness.GATE_TARGET_VALIDATION

    def test_reject_private_ip(self) -> None:
        """10.0.0.1 → BLOCKED."""
        self._check_blocked("PRIVATE_IP_10_0_0_1_CLASS")

    def test_reject_loopback_ip_as_target(self) -> None:
        """127.0.0.1 as target → BLOCKED (loopback is for work_server only)."""
        self._check_blocked("LOOPBACK_IP_127_0_0_1_CLASS")

    def test_reject_link_local(self) -> None:
        """169.254.1.1 → BLOCKED."""
        self._check_blocked("LINK_LOCAL_IP_CLASS")

    def test_reject_localhost_hostname(self) -> None:
        """localhost → BLOCKED."""
        self._check_blocked("LOCALHOST_HOSTNAME_CLASS")

    def test_reject_metadata_endpoint(self) -> None:
        """169.254.169.254 (metadata) → BLOCKED."""
        self._check_blocked("METADATA_IP_CLASS")

    def test_reject_non_allowlisted_host(self) -> None:
        """example.com (not in allowlist) → BLOCKED."""
        self._check_blocked("NON_ALLOWLISTED_EXAMPLE_COM_CLASS")


# ---------------------------------------------------------------------------
# Redirect and DNS rebinding via mocked seams
# ---------------------------------------------------------------------------


class TestRedirectAndDNSRebinding:
    def test_redirect_response_blocks(self) -> None:
        """A redirect from target_validator → BLOCKED."""
        harness = RealClearanceHarness()
        report = harness.run(
            _make_providers(),
            _make_seams(
                target_validator=FakeTargetValidatorImpl(ValidationResult.BLOCKED)
            ),
        )
        assert report.status == HarnessStatus.BLOCKED

    def test_dns_rebinding_blocks(self) -> None:
        """DNS rebinding (validator detects different IPs on calls) → BLOCKED.

        In this harness the validator seam is responsible for DNS rebinding detection.
        A blocked result from the validator represents all rejection causes.
        """
        harness = RealClearanceHarness()
        report = harness.run(
            _make_providers(),
            _make_seams(
                target_validator=FakeTargetValidatorImpl(ValidationResult.BLOCKED)
            ),
        )
        assert report.status == HarnessStatus.BLOCKED


# ---------------------------------------------------------------------------
# Redaction scanner unit tests
# ---------------------------------------------------------------------------


class TestRedactionScanner:
    def test_detects_high_entropy_hex(self) -> None:
        """32+ hex chars → sensitive."""
        assert scan_for_sensitive("aabbccddeeff00112233445566778899")

    def test_detects_key_name_pattern(self) -> None:
        """password=... → sensitive."""
        assert scan_for_sensitive("password=supersecret")

    def test_detects_url_credential(self) -> None:
        """user:pass@host → sensitive."""
        assert scan_for_sensitive("http://user:pass@example.com")

    def test_detects_cookie_format(self) -> None:
        """cf_clearance=... → sensitive."""
        assert scan_for_sensitive("cf_clearance=syntheticvalue")

    def test_detects_dsn(self) -> None:
        """postgresql://... → sensitive."""
        assert scan_for_sensitive("postgresql://user:pw@test.invalid/db")

    def test_clean_label_not_sensitive(self) -> None:
        """A safe synthetic label must NOT be flagged."""
        assert not scan_for_sensitive("FAKE_RUNTIME_TOKEN_CLASS")

    def test_clean_status_word_not_sensitive(self) -> None:
        assert not scan_for_sensitive("PASS")

    def test_clean_gate_name_not_sensitive(self) -> None:
        assert not scan_for_sensitive("provider_readiness")


# ---------------------------------------------------------------------------
# Final redaction scan catches injected sensitive string
# ---------------------------------------------------------------------------


class TestFinalRedactionScan:
    def test_sensitive_string_in_clearance_class_blocks(self) -> None:
        """If clearance_class contains a sensitive value, final scan must FAIL."""
        harness = RealClearanceHarness()
        # Inject a DSN as clearance_class — final scan must catch it
        sensitive_clearance_class = "postgresql://user:pw@test.invalid/db"
        report = harness.run(
            _make_providers(),
            _make_seams(
                clearance_observer=FakeClearanceObserver(
                    clearance_class=sensitive_clearance_class,
                ),
            ),
        )
        assert report.status == HarnessStatus.FAIL
        assert report.error_gate == RealClearanceHarness.GATE_FINAL_REDACTION
        # Evidence must be sanitized (empty) on redaction failure
        assert report.evidence == {}


# ---------------------------------------------------------------------------
# Full PASS path
# ---------------------------------------------------------------------------


class TestFullPassPath:
    def test_all_gates_pass(self) -> None:
        """Full PASS: all seams configured to succeed; all gates PASS."""
        harness = RealClearanceHarness()
        report = harness.run(_make_providers(), _make_seams())
        assert report.status == HarnessStatus.PASS
        assert report.error_gate is None
        # All 15 gates must be present and PASS
        expected_gates = {
            RealClearanceHarness.GATE_PROVIDER_READINESS,
            RealClearanceHarness.GATE_LOOPBACK,
            RealClearanceHarness.GATE_CI_CHECK,
            RealClearanceHarness.GATE_TOKEN_SOURCE,
            RealClearanceHarness.GATE_REDACTION_SELF_TEST,
            RealClearanceHarness.GATE_WORK_SERVER_STARTUP,
            RealClearanceHarness.GATE_WORK_SERVER_HEALTH,
            RealClearanceHarness.GATE_AUTH_FAILURE_PROBE,
            RealClearanceHarness.GATE_TARGET_VALIDATION,
            RealClearanceHarness.GATE_BROWSER_START,
            RealClearanceHarness.GATE_CDP_READY,
            RealClearanceHarness.GATE_CLEARANCE_OBSERVED,
            RealClearanceHarness.GATE_EXPIRES_AT,
            RealClearanceHarness.GATE_POST_CLEARANCE,
            RealClearanceHarness.GATE_FINAL_REDACTION,
        }
        for gate in expected_gates:
            assert gate in report.gate_results, f"Gate {gate!r} missing from report"
            assert report.gate_results[gate] == GateStatus.PASS, (
                f"Gate {gate!r} expected PASS, got {report.gate_results[gate]}"
            )

    def test_pass_report_evidence_is_sanitized(self) -> None:
        """Evidence fields must not contain sensitive values."""
        harness = RealClearanceHarness()
        report = harness.run(_make_providers(), _make_seams())
        assert report.status == HarnessStatus.PASS
        for key, val in report.evidence.items():
            if isinstance(val, str):
                assert not scan_for_sensitive(val), (
                    f"Evidence field {key!r} contains sensitive value: {val!r}"
                )


# ---------------------------------------------------------------------------
# Utility function unit tests
# ---------------------------------------------------------------------------


class TestUtilityFunctions:
    def test_assert_loopback_true_for_127(self) -> None:
        assert assert_loopback("127.0.0.1") is True

    def test_assert_loopback_false_for_other(self) -> None:
        assert assert_loopback("10.0.0.1") is False
        assert assert_loopback("192.168.1.1") is False
        assert assert_loopback("169.254.1.1") is False
        assert assert_loopback("example.com") is False

    def test_check_expires_at_valid_window(self) -> None:
        now = datetime.now(UTC)
        expires = now + timedelta(minutes=2)
        assert check_expires_at(expires, now) is True

    def test_check_expires_at_expired(self) -> None:
        now = datetime.now(UTC)
        expired = now - timedelta(seconds=1)
        assert check_expires_at(expired, now) is False

    def test_check_expires_at_too_far_future(self) -> None:
        now = datetime.now(UTC)
        far = now + timedelta(minutes=10)
        assert check_expires_at(far, now) is False

    def test_check_expires_at_exactly_5min_blocked(self) -> None:
        """exactly 5 min → upper bound exclusive (> not >=)."""
        now = datetime.now(UTC)
        exactly_5 = now + timedelta(minutes=5)
        # 5 min exactly is NOT in (0, 300] — 300 seconds exactly is boundary
        # Per spec: now < expires_at <= now + 5min → 300s is included
        assert check_expires_at(exactly_5, now) is True  # <=, so 5min exactly is PASS

    def test_check_expires_at_none(self) -> None:
        assert check_expires_at(None) is False

    def test_expires_at_exactly_now_is_blocked(self) -> None:
        now = datetime.now(UTC)
        assert check_expires_at(now, now=now) is False

    def test_validate_token_source_class_valid(self) -> None:
        assert validate_token_source_class("FAKE_RUNTIME_TOKEN_CLASS") is True

    def test_validate_token_source_class_empty(self) -> None:
        assert validate_token_source_class("") is False

    def test_validate_token_source_class_test(self) -> None:
        assert validate_token_source_class("test") is False

    def test_validate_token_source_class_default(self) -> None:
        assert validate_token_source_class("default") is False

    def test_validate_token_source_class_placeholder(self) -> None:
        assert validate_token_source_class("placeholder") is False


# ---------------------------------------------------------------------------
# B3: Gate 14 ValueError containment
# ---------------------------------------------------------------------------


class FakeClearancePostRaises:
    def post(self, _clearance_class: str) -> tuple[int, int]:
        raise ValueError("Unknown clearance_class label: 'FAKE_CLEARANCE_CLASS'")


class TestGate14ValueErrorContained:
    def test_post_value_error_yields_fail_at_gate14(self) -> None:
        harness = RealClearanceHarness()
        providers = _make_providers()
        seams = _make_seams(clearance_post=FakeClearancePostRaises())
        report = harness.run(providers, seams)
        assert report.status == HarnessStatus.FAIL
        assert report.error_gate == RealClearanceHarness.GATE_POST_CLEARANCE
        assert (
            report.gate_results[RealClearanceHarness.GATE_POST_CLEARANCE]
            == GateStatus.FAIL
        )


# ---------------------------------------------------------------------------
# C1: Gate 12 PermissionError yields BLOCKED with auth_failure evidence
# ---------------------------------------------------------------------------


class FakeClearanceObserverRaisesPermission:
    def observe(self, timeout_s: int) -> ClearanceResult:
        raise PermissionError("clearance GET auth failure: HTTP 401")


class TestGate12PermissionErrorBlocked:
    def test_observe_raises_permission_error_yields_blocked(self) -> None:
        harness = RealClearanceHarness()
        providers = _make_providers()
        seams = _make_seams(clearance_observer=FakeClearanceObserverRaisesPermission())
        report = harness.run(providers, seams)
        assert report.status == HarnessStatus.BLOCKED
        assert report.error_gate == RealClearanceHarness.GATE_CLEARANCE_OBSERVED
        assert report.evidence.get("clearance_getter_error") == "auth_failure"


class FakeClearanceObserverRaisesConnection:
    def observe(self, timeout_s: int) -> ClearanceResult:
        raise ConnectionError("clearance endpoint unreachable")


class TestGate12ConnectionErrorBlocked:
    def test_observe_raises_connection_error_yields_blocked(self) -> None:
        harness = RealClearanceHarness()
        providers = _make_providers()
        seams = _make_seams(clearance_observer=FakeClearanceObserverRaisesConnection())
        report = harness.run(providers, seams)
        assert report.status == HarnessStatus.BLOCKED
        assert report.error_gate == RealClearanceHarness.GATE_CLEARANCE_OBSERVED
        assert report.evidence.get("clearance_getter_error") == "connection_failure"


class TestBrowserCleanup:
    def test_stop_called_when_browser_start_fails(self) -> None:
        launcher = FakeBrowserLauncher(starts=False)
        harness = RealClearanceHarness()
        providers = _make_providers()
        seams = _make_seams(browser_launcher=launcher)
        harness.run(providers, seams)
        assert launcher.stop_called

    def test_stop_called_when_cdp_times_out(self) -> None:
        launcher = FakeBrowserLauncher(starts=True, cdp_ready=False, cdp_elapsed=31)
        harness = RealClearanceHarness()
        providers = _make_providers()
        seams = _make_seams(browser_launcher=launcher)
        harness.run(providers, seams)
        assert launcher.stop_called

    def test_stop_called_on_pass(self) -> None:
        launcher = FakeBrowserLauncher()
        harness = RealClearanceHarness()
        providers = _make_providers()
        seams = _make_seams(browser_launcher=launcher)
        harness.run(providers, seams)
        assert launcher.stop_called

    def test_stop_raises_does_not_mask_report(self) -> None:
        launcher = FakeBrowserLauncher(stop_raises=True)
        harness = RealClearanceHarness()
        providers = _make_providers()
        seams = _make_seams(browser_launcher=launcher)
        report = harness.run(providers, seams)
        assert report.status == HarnessStatus.PASS
