from __future__ import annotations

import json

from cli.smoke_clearance_real import (
    CICheckResult,
    GateStatus,
    HarnessStatus,
    RealClearanceHarness,
    RealClearanceProviders,
    RealClearanceSeams,
    ValidationResult,
)

# --- TargetProvider ---


class TestEnvTargetProvider:
    def test_ready_when_host_set(self, monkeypatch):
        monkeypatch.setenv("SCRAPING__WORK_SERVER_HOST", "127.0.0.1")
        from cli.clearance_providers import EnvTargetProvider

        assert EnvTargetProvider().is_ready() is True

    def test_not_ready_when_host_empty(self, monkeypatch):
        monkeypatch.setenv("SCRAPING__WORK_SERVER_HOST", "")
        from cli.clearance_providers import EnvTargetProvider

        assert EnvTargetProvider().is_ready() is False

    def test_not_ready_when_host_missing(self, monkeypatch):
        monkeypatch.delenv("SCRAPING__WORK_SERVER_HOST", raising=False)
        from cli.clearance_providers import EnvTargetProvider

        assert EnvTargetProvider().is_ready() is False

    def test_not_ready_when_host_whitespace_only(self, monkeypatch):
        monkeypatch.setenv("SCRAPING__WORK_SERVER_HOST", "   ")
        from cli.clearance_providers import EnvTargetProvider

        assert EnvTargetProvider().is_ready() is False

    def test_source_class_is_label_only(self, monkeypatch):
        monkeypatch.setenv("SCRAPING__WORK_SERVER_HOST", "192.168.1.99")
        from cli.clearance_providers import EnvTargetProvider

        sc = EnvTargetProvider().source_class()
        assert sc == "env:SCRAPING__WORK_SERVER_HOST"
        assert "192.168.1.99" not in sc


# --- TokenProvider ---


class TestEnvTokenProvider:
    def test_ready_when_token_set(self, monkeypatch):
        monkeypatch.setenv("SCRAPING__WORK_SERVER_TOKEN", "synthetic-token-value")
        from cli.clearance_providers import EnvTokenProvider

        assert EnvTokenProvider().is_ready() is True

    def test_not_ready_when_token_empty(self, monkeypatch):
        monkeypatch.setenv("SCRAPING__WORK_SERVER_TOKEN", "")
        from cli.clearance_providers import EnvTokenProvider

        assert EnvTokenProvider().is_ready() is False

    def test_not_ready_when_token_missing(self, monkeypatch):
        monkeypatch.delenv("SCRAPING__WORK_SERVER_TOKEN", raising=False)
        from cli.clearance_providers import EnvTokenProvider

        assert EnvTokenProvider().is_ready() is False

    def test_not_ready_when_token_whitespace_only(self, monkeypatch):
        monkeypatch.setenv("SCRAPING__WORK_SERVER_TOKEN", "   ")
        from cli.clearance_providers import EnvTokenProvider

        assert EnvTokenProvider().is_ready() is False

    def test_source_class_never_exposes_token_value(self, monkeypatch):
        monkeypatch.setenv("SCRAPING__WORK_SERVER_TOKEN", "fixture-token-value")
        from cli.clearance_providers import EnvTokenProvider

        sc = EnvTokenProvider().source_class()
        assert sc == "env:SCRAPING__WORK_SERVER_TOKEN"
        assert "fixture-token-value" not in sc


# --- BrowserParameterProvider ---


class TestEnvBrowserParameterProvider:
    def test_ready_when_profile_set(self, monkeypatch):
        monkeypatch.setenv(
            "SCRAPING__CHROME_PROFILE_DIR", "/tmp/synthetic-chrome-profile"
        )
        from cli.clearance_providers import EnvBrowserParameterProvider

        assert EnvBrowserParameterProvider().is_ready() is True

    def test_not_ready_when_profile_missing(self, monkeypatch):
        monkeypatch.delenv("SCRAPING__CHROME_PROFILE_DIR", raising=False)
        from cli.clearance_providers import EnvBrowserParameterProvider

        assert EnvBrowserParameterProvider().is_ready() is False

    def test_not_ready_when_profile_whitespace_only(self, monkeypatch):
        monkeypatch.setenv("SCRAPING__CHROME_PROFILE_DIR", "   ")
        from cli.clearance_providers import EnvBrowserParameterProvider

        assert EnvBrowserParameterProvider().is_ready() is False

    def test_validate_against_allowlist_pass(self, monkeypatch):
        monkeypatch.setenv("SCRAPING__CHROME_PROFILE_DIR", "/tmp/profile")
        from cli.clearance_providers import EnvBrowserParameterProvider

        provider = EnvBrowserParameterProvider()
        assert (
            provider.validate_against_allowlist(frozenset({provider.source_class()}))
            is True
        )

    def test_validate_against_allowlist_fail_empty(self, monkeypatch):
        monkeypatch.setenv("SCRAPING__CHROME_PROFILE_DIR", "/tmp/profile")
        from cli.clearance_providers import EnvBrowserParameterProvider

        assert (
            EnvBrowserParameterProvider().validate_against_allowlist(frozenset())
            is False
        )

    def test_validate_against_allowlist_fail_wrong_label(self, monkeypatch):
        monkeypatch.setenv("SCRAPING__CHROME_PROFILE_DIR", "/tmp/profile")
        from cli.clearance_providers import EnvBrowserParameterProvider

        assert (
            EnvBrowserParameterProvider().validate_against_allowlist(
                frozenset({"env:OTHER_LABEL"})
            )
            is False
        )

    def test_source_class_is_label_only(self, monkeypatch):
        monkeypatch.setenv(
            "SCRAPING__CHROME_PROFILE_DIR", "/tmp/synthetic-profile-path"
        )
        from cli.clearance_providers import EnvBrowserParameterProvider

        sc = EnvBrowserParameterProvider().source_class()
        assert sc == "env:SCRAPING__CHROME_PROFILE_DIR"
        assert "/tmp/synthetic-profile-path" not in sc


# --- TargetValidator ---


class TestLabelTargetValidator:
    def test_valid_known_class_passes(self):
        from cli.clearance_providers import LabelTargetValidator

        result = LabelTargetValidator().validate("env:SCRAPING__WORK_SERVER_HOST")
        assert result == ValidationResult.VALID

    def test_invalid_class_blocked(self):
        from cli.clearance_providers import LabelTargetValidator

        result = LabelTargetValidator().validate("unknown:something")
        assert result == ValidationResult.BLOCKED

    def test_empty_class_blocked(self):
        from cli.clearance_providers import LabelTargetValidator

        result = LabelTargetValidator().validate("")
        assert result == ValidationResult.BLOCKED

    def test_placeholder_class_blocked(self):
        from cli.clearance_providers import LabelTargetValidator

        result = LabelTargetValidator().validate("test")
        assert result == ValidationResult.BLOCKED

    def test_prefix_of_valid_class_blocked(self):
        from cli.clearance_providers import LabelTargetValidator

        result = LabelTargetValidator().validate("env:SCRAPING__WORK_SERVER_HOS")
        assert result == ValidationResult.BLOCKED

    def test_superset_of_valid_class_blocked(self):
        from cli.clearance_providers import LabelTargetValidator

        result = LabelTargetValidator().validate("env:SCRAPING__WORK_SERVER_HOST_EXTRA")
        assert result == ValidationResult.BLOCKED


# --- Harness gate-1 composition ---


class TestProvidersComposeWithHarnessGate1:
    def test_gate1_records_pass_even_when_downstream_blocked(self, monkeypatch):
        monkeypatch.setenv("SCRAPING__WORK_SERVER_HOST", "127.0.0.1")
        monkeypatch.setenv("SCRAPING__WORK_SERVER_TOKEN", "synthetic-gate1-token")
        monkeypatch.setenv("SCRAPING__CHROME_PROFILE_DIR", "/tmp/gate1-profile")

        from cli.clearance_providers import (
            EnvBrowserParameterProvider,
            EnvTargetProvider,
            EnvTokenProvider,
        )

        class _FakeCICheck:
            def check_once(self):
                return CICheckResult.BLOCKED  # stops at gate 3

        class _FakeWorkServer:
            def startup(self, timeout_s):
                pass

            def health_check(self):
                return False

            def auth_failure_probe(self):
                return 999

            def shutdown(self):
                pass

        class _FakeTargetValidator:
            def validate(self, target_class):
                return ValidationResult.VALID

        class _FakeBrowserLauncher:
            def start(self):
                return False

            def wait_cdp_ready(self, timeout_s):
                return (False, 0)

            def stop(self) -> None:
                pass

        class _FakeClearanceObserver:
            def observe(self, timeout_s):
                from cli.smoke_clearance_real import ClearanceResult

                return ClearanceResult(
                    obtained=False, expires_at=None, clearance_class="test"
                )

        class _FakeClearancePostClient:
            def post(self, clearance_class):
                return (500, 0)

        providers = RealClearanceProviders(
            target=EnvTargetProvider(),
            browser_params=EnvBrowserParameterProvider(),
            token=EnvTokenProvider(),
        )
        seams = RealClearanceSeams(
            ci_check=_FakeCICheck(),
            work_server=_FakeWorkServer(),
            target_validator=_FakeTargetValidator(),
            browser_launcher=_FakeBrowserLauncher(),
            clearance_observer=_FakeClearanceObserver(),
            clearance_post=_FakeClearancePostClient(),
        )
        report = RealClearanceHarness().run(providers, seams)
        # Gate 1 records PASS; harness is BLOCKED at gate 3 (ci_check returns BLOCKED).
        assert report.gate_results.get("provider_readiness") == GateStatus.PASS
        assert report.status == HarnessStatus.BLOCKED

    def test_unready_provider_blocks_gate1(self, monkeypatch):
        monkeypatch.delenv("SCRAPING__WORK_SERVER_TOKEN", raising=False)
        monkeypatch.setenv("SCRAPING__WORK_SERVER_HOST", "127.0.0.1")
        monkeypatch.setenv("SCRAPING__CHROME_PROFILE_DIR", "/tmp/profile")

        from cli.clearance_providers import (
            EnvBrowserParameterProvider,
            EnvTargetProvider,
            EnvTokenProvider,
        )

        class _StubCICheck:
            def check_once(self):
                return CICheckResult.ALL_PASS

        class _StubWorkServer:
            def startup(self, timeout_s):
                pass

            def health_check(self):
                return True

            def auth_failure_probe(self):
                return 401

            def shutdown(self):
                pass

        class _StubTargetValidator:
            def validate(self, target_class):
                return ValidationResult.VALID

        class _StubBrowserLauncher:
            def start(self):
                return True

            def wait_cdp_ready(self, timeout_s):
                return (True, 1)

            def stop(self) -> None:
                pass

        class _StubClearanceObserver:
            def observe(self, timeout_s):
                from cli.smoke_clearance_real import ClearanceResult

                return ClearanceResult(
                    obtained=False, expires_at=None, clearance_class="test"
                )

        class _StubClearancePostClient:
            def post(self, clearance_class):
                return (500, 0)

        providers = RealClearanceProviders(
            target=EnvTargetProvider(),
            browser_params=EnvBrowserParameterProvider(),
            token=EnvTokenProvider(),
        )
        seams = RealClearanceSeams(
            ci_check=_StubCICheck(),
            work_server=_StubWorkServer(),
            target_validator=_StubTargetValidator(),
            browser_launcher=_StubBrowserLauncher(),
            clearance_observer=_StubClearanceObserver(),
            clearance_post=_StubClearancePostClient(),
        )
        report = RealClearanceHarness().run(providers, seams)
        assert report.gate_results.get("provider_readiness") == GateStatus.BLOCKED
        assert report.status == HarnessStatus.BLOCKED


# ---------------------------------------------------------------------------
# B2: GhCICheckProvider workflow filter
# ---------------------------------------------------------------------------


def _fake_runner_with(
    workflow_name: str,
    status: str = "completed",
    conclusion: str = "success",
):
    def _runner(cmd):
        runs = [{"headBranch": "main", "status": status, "conclusion": conclusion,
                 "workflowName": workflow_name, "createdAt": "2026-08-26T10:00:00Z"}]
        return (0, json.dumps(runs))
    return _runner


class TestGhCICheckProviderWorkflowFilter:
    def test_non_ci_workflow_run_blocked(self):
        from cli.clearance_providers import GhCICheckProvider
        from cli.smoke_clearance_real import CICheckResult
        provider = GhCICheckProvider(
            runner=_fake_runner_with("Release"),
            workflow_name="CI",
        )
        assert provider.check_once() == CICheckResult.BLOCKED

    def test_ci_workflow_run_passes(self):
        from cli.clearance_providers import GhCICheckProvider
        from cli.smoke_clearance_real import CICheckResult
        provider = GhCICheckProvider(
            runner=_fake_runner_with("CI"),
            workflow_name="CI",
        )
        assert provider.check_once() == CICheckResult.ALL_PASS

    def test_ci_workflow_in_progress_blocked(self):
        from cli.clearance_providers import GhCICheckProvider
        from cli.smoke_clearance_real import CICheckResult
        provider = GhCICheckProvider(
            runner=_fake_runner_with("CI", status="in_progress"),
            workflow_name="CI",
        )
        assert provider.check_once() == CICheckResult.BLOCKED

    def test_workflow_name_none_not_filtered(self):
        from cli.clearance_providers import GhCICheckProvider
        from cli.smoke_clearance_real import CICheckResult
        provider = GhCICheckProvider(
            runner=_fake_runner_with("Release"),
            workflow_name=None,
        )
        assert provider.check_once() == CICheckResult.ALL_PASS
