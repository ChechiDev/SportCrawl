"""Unit tests for RealWorkServerLifecycle — fully synthetic, no real server."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest
import requests

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
from cli.work_server_lifecycle import RealWorkServerLifecycle

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_OK_BODY = {"status": "ok"}


def _make_mock_response(
    status_code: int,
    json_body: dict[str, str] | list[Any] | None = None,
    json_raises: type[Exception] | None = None,
) -> MagicMock:
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    if json_raises is not None:
        resp.json.side_effect = json_raises
    elif json_body is not None:
        resp.json.return_value = json_body
    return resp


def _ok_health() -> MagicMock:
    return MagicMock(return_value=_make_mock_response(200, _OK_BODY))


def _make_lifecycle(
    *,
    health_getter: Any = None,
    clearance_poster: Any = None,
    process_starter: Any = None,
    clock: Any = None,
    sleeper: Any = None,
) -> RealWorkServerLifecycle:
    if health_getter is None:
        health_getter = _ok_health()
    if clearance_poster is None:
        clearance_poster = MagicMock(return_value=_make_mock_response(401))
    if process_starter is None:
        process_starter = MagicMock(return_value=MagicMock(spec=subprocess.Popen))
    kwargs: dict[str, Any] = {}
    if clock is not None:
        kwargs["clock"] = clock
    if sleeper is not None:
        kwargs["sleeper"] = sleeper
    return RealWorkServerLifecycle(
        host="127.0.0.1",
        port=9731,
        token="__test_token__",
        cmd=["fake-server"],
        process_starter=process_starter,
        health_getter=health_getter,
        clearance_poster=clearance_poster,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# startup
# ---------------------------------------------------------------------------


class TestStartup:
    def test_startup_raises_timeout_when_health_never_succeeds(self) -> None:
        def _past_deadline() -> float:
            return float("inf")

        lc = _make_lifecycle(
            health_getter=MagicMock(side_effect=ConnectionRefusedError("no server")),
            clock=_past_deadline,
            sleeper=MagicMock(),
        )
        with pytest.raises(TimeoutError, match="work_server did not become healthy"):
            lc.startup(timeout_s=0)

    def test_startup_succeeds_when_health_becomes_ready(self) -> None:
        process_starter = MagicMock(return_value=MagicMock(spec=subprocess.Popen))
        mock_sleeper = MagicMock()
        lc = _make_lifecycle(
            health_getter=_ok_health(),
            process_starter=process_starter,
            sleeper=mock_sleeper,
        )
        lc.startup(timeout_s=5)
        process_starter.assert_called_once()
        mock_sleeper.assert_not_called()


# ---------------------------------------------------------------------------
# health_check
# ---------------------------------------------------------------------------


class TestHealthCheck:
    def test_health_check_true_on_200_ok_body(self) -> None:
        lc = _make_lifecycle(
            health_getter=MagicMock(
                return_value=_make_mock_response(200, _OK_BODY)
            )
        )
        assert lc.health_check() is True

    def test_health_check_false_on_non_200(self) -> None:
        lc = _make_lifecycle(
            health_getter=MagicMock(
                return_value=_make_mock_response(503, {"status": "error"})
            )
        )
        assert lc.health_check() is False

    def test_health_check_false_on_exception(self) -> None:
        lc = _make_lifecycle(
            health_getter=MagicMock(side_effect=ConnectionError("down"))
        )
        assert lc.health_check() is False

    def test_health_check_false_on_non_dict_body(self) -> None:
        lc = _make_lifecycle(
            health_getter=MagicMock(
                return_value=_make_mock_response(200, json_body=[])
            )
        )
        assert lc.health_check() is False

    def test_health_check_false_on_dict_missing_ok_status(self) -> None:
        lc = _make_lifecycle(
            health_getter=MagicMock(
                return_value=_make_mock_response(200, json_body={"status": "degraded"})
            )
        )
        assert lc.health_check() is False

    def test_health_check_false_when_json_raises(self) -> None:
        lc = _make_lifecycle(
            health_getter=MagicMock(
                return_value=_make_mock_response(200, json_raises=ValueError)
            )
        )
        assert lc.health_check() is False


# ---------------------------------------------------------------------------
# auth_failure_probe
# ---------------------------------------------------------------------------


class TestAuthFailureProbe:
    def test_auth_failure_probe_returns_401(self) -> None:
        lc = _make_lifecycle(
            clearance_poster=MagicMock(return_value=_make_mock_response(401))
        )
        assert lc.auth_failure_probe() == 401

    def test_auth_failure_probe_returns_non_401_for_misconfiguration(self) -> None:
        lc = _make_lifecycle(
            clearance_poster=MagicMock(return_value=_make_mock_response(200))
        )
        assert lc.auth_failure_probe() == 200

    def test_auth_failure_probe_returns_0_on_exception(self) -> None:
        lc = _make_lifecycle(
            clearance_poster=MagicMock(side_effect=ConnectionError("down"))
        )
        assert lc.auth_failure_probe() == 0

    def test_auth_failure_probe_sends_garbage_token_header(self) -> None:
        poster = MagicMock(return_value=_make_mock_response(401))
        lc = _make_lifecycle(clearance_poster=poster)
        lc.auth_failure_probe()
        _, headers = poster.call_args[0]
        assert headers["Authorization"] == "Bearer __smoke_probe__"

    def test_auth_failure_probe_does_not_send_real_token(self) -> None:
        poster = MagicMock(return_value=_make_mock_response(401))
        lc = _make_lifecycle(clearance_poster=poster)
        lc.auth_failure_probe()
        _, headers = poster.call_args[0]
        assert "__test_token__" not in headers["Authorization"]


# ---------------------------------------------------------------------------
# shutdown
# ---------------------------------------------------------------------------


class TestShutdown:
    def test_shutdown_tolerates_no_process(self) -> None:
        lc = _make_lifecycle()
        lc.shutdown()

    def test_shutdown_terminates_and_waits(self) -> None:
        proc = MagicMock(spec=subprocess.Popen)
        lc = _make_lifecycle(
            process_starter=MagicMock(return_value=proc),
            health_getter=_ok_health(),
        )
        lc.startup(timeout_s=5)
        lc.shutdown()
        proc.terminate.assert_called_once()
        proc.wait.assert_called_once()

    def test_shutdown_kills_after_wait_timeout(self) -> None:
        proc = MagicMock(spec=subprocess.Popen)
        proc.wait.side_effect = subprocess.TimeoutExpired(cmd="fake", timeout=3)
        lc = _make_lifecycle(
            process_starter=MagicMock(return_value=proc),
            health_getter=_ok_health(),
        )
        lc.startup(timeout_s=5)
        lc.shutdown()
        proc.kill.assert_called_once()

    def test_shutdown_swallows_cleanup_exceptions(self) -> None:
        proc = MagicMock(spec=subprocess.Popen)
        proc.terminate.side_effect = OSError("no such process")
        lc = _make_lifecycle(
            process_starter=MagicMock(return_value=proc),
            health_getter=_ok_health(),
        )
        lc.startup(timeout_s=5)
        lc.shutdown()  # must not raise

    def test_shutdown_swallows_kill_exception_after_wait_timeout(self) -> None:
        proc = MagicMock(spec=subprocess.Popen)
        proc.wait.side_effect = subprocess.TimeoutExpired(cmd="fake", timeout=3)
        proc.kill.side_effect = OSError("already dead")
        lc = _make_lifecycle(
            process_starter=MagicMock(return_value=proc),
            health_getter=_ok_health(),
        )
        lc.startup(timeout_s=5)
        lc.shutdown()  # must not raise


# ---------------------------------------------------------------------------
# Harness integration stubs
# ---------------------------------------------------------------------------


class _FakeTargetProvider:
    def is_ready(self) -> bool:
        return True

    def source_class(self) -> str:
        return "FAKE_RUNTIME_TARGET_CLASS"


class _FakeBrowserParamProvider:
    def is_ready(self) -> bool:
        return True

    def source_class(self) -> str:
        return "FAKE_RUNTIME_BROWSER_PARAM_CLASS"

    def validate_against_allowlist(  # noqa: ARG002
        self, _allowlist: frozenset[str]
    ) -> bool:
        return True


class _FakeTokenProvider:
    def is_ready(self) -> bool:
        return True

    def source_class(self) -> str:
        return "FAKE_RUNTIME_TOKEN_CLASS"


class _FakeCICheck:
    def check_once(self) -> CICheckResult:
        return CICheckResult.ALL_PASS


class _FakeTargetValidator:
    def validate(self, _target_class: str) -> ValidationResult:  # noqa: ARG002
        return ValidationResult.VALID


class _FakeBrowserLauncher:
    def start(self) -> bool:
        return True

    def wait_cdp_ready(self, timeout_s: int) -> tuple[bool, int]:  # noqa: ARG002
        return True, 5


class _FakeClearanceObserver:
    def observe(self, timeout_s: int) -> ClearanceResult:  # noqa: ARG002
        return ClearanceResult(
            obtained=True,
            expires_at=datetime.now(UTC) + timedelta(minutes=2),
            clearance_class="FAKE_CLEARANCE_CLASS",
        )


class _FakeClearancePost:
    def post(self, _clearance_class: str) -> tuple[int, int]:  # noqa: ARG002
        return 204, 0


def _make_providers() -> RealClearanceProviders:
    return RealClearanceProviders(
        target=_FakeTargetProvider(),  # type: ignore[arg-type]
        browser_params=_FakeBrowserParamProvider(),  # type: ignore[arg-type]
        token=_FakeTokenProvider(),  # type: ignore[arg-type]
    )


def _make_seams(work_server: Any) -> RealClearanceSeams:
    return RealClearanceSeams(
        ci_check=_FakeCICheck(),  # type: ignore[arg-type]
        work_server=work_server,
        target_validator=_FakeTargetValidator(),  # type: ignore[arg-type]
        browser_launcher=_FakeBrowserLauncher(),  # type: ignore[arg-type]
        clearance_observer=_FakeClearanceObserver(),  # type: ignore[arg-type]
        clearance_post=_FakeClearancePost(),  # type: ignore[arg-type]
        resolved_host="127.0.0.1",
    )


class _WorkServerStub:
    def __init__(
        self,
        startup_raises: bool = False,
        health: bool = True,
        auth_probe: int = 401,
    ) -> None:
        self._startup_raises = startup_raises
        self._health = health
        self._auth_probe = auth_probe

    def startup(self, timeout_s: int) -> None:  # noqa: ARG002
        if self._startup_raises:
            raise TimeoutError("work_server did not become healthy")

    def health_check(self) -> bool:
        return self._health

    def auth_failure_probe(self) -> int:
        return self._auth_probe

    def shutdown(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Harness integration — gates 7, 8, 9
# ---------------------------------------------------------------------------


class TestHarnessWorkServerGates:
    def test_harness_gate7_blocks_on_startup_raise(self) -> None:
        ws = _WorkServerStub(startup_raises=True)
        report = RealClearanceHarness().run(_make_providers(), _make_seams(ws))
        gate = RealClearanceHarness.GATE_WORK_SERVER_STARTUP
        assert report.gate_results.get(gate) == GateStatus.BLOCKED
        assert report.status == HarnessStatus.BLOCKED
        assert report.error_gate == gate

    def test_harness_gate8_blocks_on_failed_health(self) -> None:
        ws = _WorkServerStub(health=False)
        report = RealClearanceHarness().run(_make_providers(), _make_seams(ws))
        gate = RealClearanceHarness.GATE_WORK_SERVER_HEALTH
        assert report.gate_results.get(gate) == GateStatus.BLOCKED
        assert report.status == HarnessStatus.BLOCKED
        assert report.error_gate == gate

    def test_harness_gate9_blocks_on_non_401_probe(self) -> None:
        ws = _WorkServerStub(auth_probe=200)
        report = RealClearanceHarness().run(_make_providers(), _make_seams(ws))
        gate = RealClearanceHarness.GATE_AUTH_FAILURE_PROBE
        assert report.gate_results.get(gate) == GateStatus.BLOCKED
        assert report.status == HarnessStatus.BLOCKED
        assert report.error_gate == gate
