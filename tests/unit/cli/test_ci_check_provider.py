from __future__ import annotations

import json

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
# Helpers
# ---------------------------------------------------------------------------


def _runner_ok(runs: list[dict]) -> tuple[int, str]:
    return (0, json.dumps(runs))


def _make_run(
    status: str,
    conclusion: str | None,
    branch: str = "main",
    workflow: str = "CI",
    created_at: str = "2026-08-25T12:00:00Z",
) -> dict:
    return {
        "headBranch": branch,
        "status": status,
        "conclusion": conclusion,
        "workflowName": workflow,
        "createdAt": created_at,
    }


# ---------------------------------------------------------------------------
# Stub seam helpers for harness composition tests
# ---------------------------------------------------------------------------


class _PassTargetProvider:
    def is_ready(self) -> bool:
        return True

    def source_class(self) -> str:
        return "env:SCRAPING__WORK_SERVER_HOST"


class _PassTokenProvider:
    def is_ready(self) -> bool:
        return True

    def source_class(self) -> str:
        return "env:SCRAPING__WORK_SERVER_TOKEN"


class _PassBrowserParamsProvider:
    def is_ready(self) -> bool:
        return True

    def source_class(self) -> str:
        return "env:SCRAPING__CHROME_PROFILE_DIR"

    def validate_against_allowlist(self, allowlist: frozenset[str]) -> bool:
        return True


class _PassWorkServer:
    def startup(self, timeout_s: int) -> None:
        pass

    def health_check(self) -> bool:
        return True

    def auth_failure_probe(self) -> int:
        return 401

    def shutdown(self) -> None:
        pass


class _PassTargetValidator:
    def validate(self, target_class: str) -> ValidationResult:
        return ValidationResult.VALID


class _PassBrowserLauncher:
    def start(self) -> bool:
        return True

    def wait_cdp_ready(self, timeout_s: int) -> tuple[bool, int]:
        return (True, 1)


class _PassClearanceObserver:
    def observe(self, timeout_s: int) -> ClearanceResult:
        from datetime import UTC, datetime, timedelta

        return ClearanceResult(
            obtained=True,
            expires_at=datetime.now(UTC) + timedelta(seconds=60),
            clearance_class="env:SCRAPING__CHROME_PROFILE_DIR",
        )


class _PassClearancePostClient:
    def post(self, clearance_class: str) -> tuple[int, int]:
        return (204, 0)


def _pass_providers() -> RealClearanceProviders:
    return RealClearanceProviders(
        target=_PassTargetProvider(),
        browser_params=_PassBrowserParamsProvider(),
        token=_PassTokenProvider(),
    )


def _pass_seams(ci_check: object) -> RealClearanceSeams:
    return RealClearanceSeams(
        ci_check=ci_check,  # type: ignore[arg-type]
        work_server=_PassWorkServer(),
        target_validator=_PassTargetValidator(),
        browser_launcher=_PassBrowserLauncher(),
        clearance_observer=_PassClearanceObserver(),
        clearance_post=_PassClearancePostClient(),
        resolved_host="127.0.0.1",
    )


# ---------------------------------------------------------------------------
# Unit tests for GhCICheckProvider
# ---------------------------------------------------------------------------


class TestGhCICheckProvider:
    def _provider(self, runner):
        from cli.clearance_providers import GhCICheckProvider

        return GhCICheckProvider(runner=runner)

    def test_returns_all_pass_for_latest_completed_success(self):
        runs = [_make_run("completed", "success")]
        provider = self._provider(lambda _: _runner_ok(runs))
        assert provider.check_once() == CICheckResult.ALL_PASS

    def test_returns_blocked_for_latest_completed_failure(self):
        runs = [_make_run("completed", "failure")]
        provider = self._provider(lambda _: _runner_ok(runs))
        assert provider.check_once() == CICheckResult.BLOCKED

    def test_returns_blocked_for_latest_completed_cancelled(self):
        runs = [_make_run("completed", "cancelled")]
        provider = self._provider(lambda _: _runner_ok(runs))
        assert provider.check_once() == CICheckResult.BLOCKED

    def test_returns_blocked_for_latest_completed_timed_out(self):
        runs = [_make_run("completed", "timed_out")]
        provider = self._provider(lambda _: _runner_ok(runs))
        assert provider.check_once() == CICheckResult.BLOCKED

    def test_returns_blocked_for_latest_completed_action_required(self):
        runs = [_make_run("completed", "action_required")]
        provider = self._provider(lambda _: _runner_ok(runs))
        assert provider.check_once() == CICheckResult.BLOCKED

    def test_returns_blocked_when_latest_run_in_progress(self):
        runs = [_make_run("in_progress", None)]
        provider = self._provider(lambda _: _runner_ok(runs))
        assert provider.check_once() == CICheckResult.BLOCKED

    def test_returns_blocked_when_latest_run_queued(self):
        runs = [_make_run("queued", None)]
        provider = self._provider(lambda _: _runner_ok(runs))
        assert provider.check_once() == CICheckResult.BLOCKED

    def test_returns_blocked_when_no_runs(self):
        provider = self._provider(lambda _: _runner_ok([]))
        assert provider.check_once() == CICheckResult.BLOCKED

    def test_returns_blocked_for_invalid_json(self):
        provider = self._provider(lambda _: (0, "not json"))
        assert provider.check_once() == CICheckResult.BLOCKED

    def test_returns_blocked_for_subprocess_nonzero_exit(self):
        provider = self._provider(lambda _: (1, ""))
        assert provider.check_once() == CICheckResult.BLOCKED

    def test_latest_completed_wins_over_earlier_in_progress(self):
        # completed success is newer; in_progress is older → ALL_PASS
        runs = [
            _make_run("in_progress", None, created_at="2026-08-25T11:00:00Z"),
            _make_run("completed", "success", created_at="2026-08-25T12:00:00Z"),
        ]
        provider = self._provider(lambda _: _runner_ok(runs))
        assert provider.check_once() == CICheckResult.ALL_PASS

    def test_latest_completed_failure_wins_over_earlier_success(self):
        # failure is newer; success is older → BLOCKED
        runs = [
            _make_run("completed", "failure", created_at="2026-08-25T12:00:00Z"),
            _make_run("completed", "success", created_at="2026-08-25T11:00:00Z"),
        ]
        provider = self._provider(lambda _: _runner_ok(runs))
        assert provider.check_once() == CICheckResult.BLOCKED

    def test_newer_success_beats_older_failure(self):
        runs = [
            _make_run("completed", "failure", created_at="2026-08-25T10:00:00Z"),
            _make_run("completed", "success", created_at="2026-08-25T12:00:00Z"),
        ]
        provider = self._provider(lambda _: _runner_ok(runs))
        assert provider.check_once() == CICheckResult.ALL_PASS

    def test_newer_failure_beats_older_success(self):
        runs = [
            _make_run("completed", "success", created_at="2026-08-25T10:00:00Z"),
            _make_run("completed", "failure", created_at="2026-08-25T12:00:00Z"),
        ]
        provider = self._provider(lambda _: _runner_ok(runs))
        assert provider.check_once() == CICheckResult.BLOCKED

    def test_newest_in_progress_blocks_even_if_older_success_exists(self):
        runs = [
            _make_run("completed", "success", created_at="2026-08-25T10:00:00Z"),
            _make_run("in_progress", None, created_at="2026-08-25T12:00:00Z"),
        ]
        provider = self._provider(lambda _: _runner_ok(runs))
        assert provider.check_once() == CICheckResult.BLOCKED

    def test_newest_queued_blocks_even_if_older_success_exists(self):
        runs = [
            _make_run("completed", "success", created_at="2026-08-25T10:00:00Z"),
            _make_run("queued", None, created_at="2026-08-25T12:00:00Z"),
        ]
        provider = self._provider(lambda _: _runner_ok(runs))
        assert provider.check_once() == CICheckResult.BLOCKED

    def test_completed_with_null_conclusion_blocks(self):
        runs = [_make_run("completed", None)]
        provider = self._provider(lambda _: _runner_ok(runs))
        assert provider.check_once() == CICheckResult.BLOCKED

    def test_runner_receives_expected_command(self):
        captured: list[list[str]] = []

        def _runner(cmd: list[str]) -> tuple[int, str]:
            captured.append(cmd)
            return _runner_ok([_make_run("completed", "success")])

        from cli.clearance_providers import GhCICheckProvider

        GhCICheckProvider(runner=_runner).check_once()
        assert captured, "runner was never called"
        assert "gh" in captured[0]
        assert "run" in captured[0]
        assert "list" in captured[0]


# ---------------------------------------------------------------------------
# Harness composition tests (gate 3)
# ---------------------------------------------------------------------------


class TestGhCICheckProviderComposesWithHarness:
    def test_composes_with_harness_gate3_all_pass(self):
        runs = [_make_run("completed", "success")]

        from cli.clearance_providers import GhCICheckProvider

        ci_check = GhCICheckProvider(runner=lambda _: _runner_ok(runs))

        report = RealClearanceHarness().run(_pass_providers(), _pass_seams(ci_check))
        assert report.gate_results.get("ci_check") == GateStatus.PASS
        assert report.status == HarnessStatus.PASS

    def test_composes_with_harness_gate3_blocked(self):
        runs = [_make_run("completed", "failure")]

        from cli.clearance_providers import GhCICheckProvider

        ci_check = GhCICheckProvider(runner=lambda _: _runner_ok(runs))

        report = RealClearanceHarness().run(_pass_providers(), _pass_seams(ci_check))
        assert report.gate_results.get("ci_check") == GateStatus.BLOCKED
        assert report.status == HarnessStatus.BLOCKED
        assert report.error_gate == "ci_check"
        assert report.gate_results.get("provider_readiness") == GateStatus.PASS
        assert report.gate_results.get("loopback_assertion") == GateStatus.PASS
