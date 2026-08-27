"""Tests for --real-clearance wireup in cli/main.py.

Verifies that the smoke-clearance --real-clearance path constructs the correct
concrete providers and seams, passes them to RealClearanceHarness.run(), and
maps HarnessStatus to the correct exit code.

All seam constructors are patched at their import path in cli.main.
No real browser, network, DB, or Docker is started.
"""

from __future__ import annotations

import http.client
import io
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from cli.main import app
from cli.smoke_clearance_real import HarnessReport, HarnessStatus

runner = CliRunner()

_CLI_MAIN = Path(__file__).parents[3] / "cli" / "main.py"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _src() -> str:
    return _CLI_MAIN.read_text(encoding="utf-8")


def _invoke_patched(
    harness_status: HarnessStatus = HarnessStatus.PASS,
) -> tuple[object, dict[str, MagicMock], MagicMock]:
    """Invoke --real-clearance with all constructors patched.

    Returns (result, mocks_dict, harness_instance).
    """
    mock_report = HarnessReport(status=harness_status)

    with (
        patch("cli.main.EnvTargetProvider") as m_target,
        patch("cli.main.EnvBrowserParameterProvider") as m_bp,
        patch("cli.main.EnvTokenProvider") as m_token,
        patch("cli.main.GhCICheckProvider") as m_ci,
        patch("cli.main.RealWorkServerLifecycle") as m_ws,
        patch("cli.main.LabelTargetValidator") as m_validator,
        patch("cli.main.RealBrowserLauncher") as m_launcher,
        patch("cli.main.RealClearanceObserver") as m_observer,
        patch("cli.main.RealClearancePostClient") as m_post,
        patch("cli.main.RealClearanceProviders") as m_providers_cls,
        patch("cli.main.RealClearanceSeams") as m_seams_cls,
        patch("cli.main.RealClearanceHarness") as m_harness_cls,
    ):
        mock_harness_inst = MagicMock()
        mock_harness_inst.run.return_value = mock_report
        m_harness_cls.return_value = mock_harness_inst

        result = runner.invoke(app, ["smoke-clearance", "--real-clearance"])
        mocks = {
            "target": m_target,
            "bp": m_bp,
            "token": m_token,
            "ci": m_ci,
            "ws": m_ws,
            "validator": m_validator,
            "launcher": m_launcher,
            "observer": m_observer,
            "post": m_post,
            "providers_cls": m_providers_cls,
            "seams_cls": m_seams_cls,
            "harness_cls": m_harness_cls,
        }
        return result, mocks, mock_harness_inst


# ---------------------------------------------------------------------------
# Source-inspection tests — no FBref literals in cli/main.py
# ---------------------------------------------------------------------------


class TestNoFBrefLiteralInMain:
    def test_no_cf_clearance_fbref_literal(self) -> None:
        """cf_clearance@fbref.com must not appear in cli/main.py.

        Domain literals belong in clearance_post_client.py.
        """
        assert "cf_clearance@fbref.com" not in _src(), (
            "cf_clearance@fbref.com must not appear in cli/main.py"
        )

    def test_no_cf_clearance_at_sign_literal(self) -> None:
        """'cf_clearance@' must not appear in cli/main.py."""
        assert "cf_clearance@" not in _src(), (
            "'cf_clearance@' must not appear in cli/main.py"
        )


# ---------------------------------------------------------------------------
# Provider construction tests
# ---------------------------------------------------------------------------


class TestRealClearanceProviderConstruction:
    """--real-clearance must construct RealClearanceProviders with the correct types."""

    def test_env_target_provider_constructed(self) -> None:
        _, mocks, _ = _invoke_patched()
        mocks["target"].assert_called_once()

    def test_env_browser_parameter_provider_constructed(self) -> None:
        _, mocks, _ = _invoke_patched()
        mocks["bp"].assert_called_once()

    def test_env_token_provider_constructed(self) -> None:
        _, mocks, _ = _invoke_patched()
        mocks["token"].assert_called_once()


# ---------------------------------------------------------------------------
# Seam construction tests
# ---------------------------------------------------------------------------


class TestRealClearanceSeamConstruction:
    """--real-clearance must construct RealClearanceSeams with the correct types."""

    def test_gh_ci_check_provider_constructed(self) -> None:
        _, mocks, _ = _invoke_patched()
        mocks["ci"].assert_called_once()

    def test_real_work_server_lifecycle_constructed(self) -> None:
        _, mocks, _ = _invoke_patched()
        mocks["ws"].assert_called_once()

    def test_label_target_validator_constructed(self) -> None:
        _, mocks, _ = _invoke_patched()
        mocks["validator"].assert_called_once()

    def test_real_browser_launcher_constructed(self) -> None:
        _, mocks, _ = _invoke_patched()
        mocks["launcher"].assert_called_once()

    def test_real_clearance_observer_constructed(self) -> None:
        _, mocks, _ = _invoke_patched()
        mocks["observer"].assert_called_once()

    def test_real_clearance_post_client_constructed(self) -> None:
        _, mocks, _ = _invoke_patched()
        mocks["post"].assert_called_once()

    def test_real_clearance_seams_constructed(self) -> None:
        _, mocks, _ = _invoke_patched()
        mocks["seams_cls"].assert_called_once()

    def test_resolved_host_is_loopback(self) -> None:
        """RealClearanceSeams must be constructed with resolved_host='127.0.0.1'."""
        _, mocks, _ = _invoke_patched()
        call_kwargs = mocks["seams_cls"].call_args
        assert call_kwargs is not None, "RealClearanceSeams was not constructed"
        kwargs = call_kwargs.kwargs if call_kwargs.kwargs else {}
        resolved_host = kwargs.get("resolved_host")
        assert resolved_host == "127.0.0.1", (
            f"resolved_host must be '127.0.0.1', got {resolved_host!r}"
        )


# ---------------------------------------------------------------------------
# Harness invocation and exit code tests
# ---------------------------------------------------------------------------


class TestRealClearanceHarnessInvocation:
    """RealClearanceHarness.run(providers, seams) must be called exactly once."""

    def test_harness_run_called_exactly_once_on_pass(self) -> None:
        _, _, harness_inst = _invoke_patched(HarnessStatus.PASS)
        assert harness_inst.run.call_count == 1, (
            f"harness.run() must be called exactly once, "
            f"got {harness_inst.run.call_count}"
        )

    def test_exit_code_0_on_pass(self) -> None:
        result, _, _ = _invoke_patched(HarnessStatus.PASS)
        code = result.exit_code  # type: ignore[union-attr]
        assert code == 0, f"Expected exit 0 on PASS, got {code}"

    def test_exit_code_1_on_blocked(self) -> None:
        result, _, _ = _invoke_patched(HarnessStatus.BLOCKED)
        code = result.exit_code  # type: ignore[union-attr]
        assert code == 1, f"Expected exit 1 on BLOCKED, got {code}"

    def test_exit_code_1_on_fail(self) -> None:
        result, _, _ = _invoke_patched(HarnessStatus.FAIL)
        code = result.exit_code  # type: ignore[union-attr]
        assert code == 1, f"Expected exit 1 on FAIL, got {code}"

    def test_harness_run_called_exactly_once_on_blocked(self) -> None:
        _, _, harness_inst = _invoke_patched(HarnessStatus.BLOCKED)
        assert harness_inst.run.call_count == 1

    def test_harness_run_called_exactly_once_on_fail(self) -> None:
        _, _, harness_inst = _invoke_patched(HarnessStatus.FAIL)
        assert harness_inst.run.call_count == 1


class TestRealClearanceConstructorArgs:
    """Verify constructor arguments are correctly wired from env/config."""

    def test_work_server_token_comes_from_env(self) -> None:
        """Token must come from SCRAPING__WORK_SERVER_TOKEN, not hardcoded."""
        import os
        env = {**os.environ, "SCRAPING__WORK_SERVER_TOKEN": "test-token-xyz"}
        with (
            patch("cli.main.EnvTargetProvider"),
            patch("cli.main.EnvBrowserParameterProvider"),
            patch("cli.main.EnvTokenProvider"),
            patch("cli.main.GhCICheckProvider"),
            patch("cli.main.RealWorkServerLifecycle") as m_ws,
            patch("cli.main.LabelTargetValidator"),
            patch("cli.main.RealBrowserLauncher"),
            patch("cli.main.RealClearanceObserver"),
            patch("cli.main.RealClearancePostClient") as m_post,
            patch("cli.main.RealClearanceProviders"),
            patch("cli.main.RealClearanceSeams"),
            patch("cli.main.RealClearanceHarness") as m_harness_cls,
        ):
            mock_report = HarnessReport(status=HarnessStatus.PASS)
            m_harness_cls.return_value.run.return_value = mock_report
            runner.invoke(
                app, ["smoke-clearance", "--real-clearance"],
                env=env, catch_exceptions=False,
            )
            ws_kwargs = m_ws.call_args.kwargs if m_ws.call_args else {}
            assert ws_kwargs.get("token") == "test-token-xyz"
            post_kwargs = m_post.call_args.kwargs if m_post.call_args else {}
            assert post_kwargs.get("token") == "test-token-xyz"

    def test_work_server_cmd_default_is_generic(self) -> None:
        """Default cmd must be ['uv', 'run', 'sportcrawl', 'work-server']."""
        import os
        env = {k: v for k, v in os.environ.items() if k != "SCRAPING__WORK_SERVER_CMD"}
        with (
            patch("cli.main.EnvTargetProvider"),
            patch("cli.main.EnvBrowserParameterProvider"),
            patch("cli.main.EnvTokenProvider"),
            patch("cli.main.GhCICheckProvider"),
            patch("cli.main.RealWorkServerLifecycle") as m_ws,
            patch("cli.main.LabelTargetValidator"),
            patch("cli.main.RealBrowserLauncher"),
            patch("cli.main.RealClearanceObserver"),
            patch("cli.main.RealClearancePostClient"),
            patch("cli.main.RealClearanceProviders"),
            patch("cli.main.RealClearanceSeams"),
            patch("cli.main.RealClearanceHarness") as m_harness_cls,
        ):
            mock_report = HarnessReport(status=HarnessStatus.PASS)
            m_harness_cls.return_value.run.return_value = mock_report
            runner.invoke(
                app, ["smoke-clearance", "--real-clearance"],
                env=env, catch_exceptions=False,
            )
            ws_kwargs = m_ws.call_args.kwargs if m_ws.call_args else {}
            assert ws_kwargs.get("cmd") == ["uv", "run", "sportcrawl", "work-server"]

    def test_clearance_post_url_uses_loopback(self) -> None:
        """RealClearancePostClient url must use 127.0.0.1 loopback — not env host."""
        with (
            patch("cli.main.EnvTargetProvider"),
            patch("cli.main.EnvBrowserParameterProvider"),
            patch("cli.main.EnvTokenProvider"),
            patch("cli.main.GhCICheckProvider"),
            patch("cli.main.RealWorkServerLifecycle"),
            patch("cli.main.LabelTargetValidator"),
            patch("cli.main.RealBrowserLauncher"),
            patch("cli.main.RealClearanceObserver"),
            patch("cli.main.RealClearancePostClient") as m_post,
            patch("cli.main.RealClearanceProviders"),
            patch("cli.main.RealClearanceSeams"),
            patch("cli.main.RealClearanceHarness") as m_harness_cls,
        ):
            mock_report = HarnessReport(status=HarnessStatus.PASS)
            m_harness_cls.return_value.run.return_value = mock_report
            runner.invoke(app, ["smoke-clearance", "--real-clearance"])
            post_kwargs = m_post.call_args.kwargs if m_post.call_args else {}
            url = post_kwargs.get("url", "")
            assert "127.0.0.1" in url, f"URL must use 127.0.0.1 loopback, got: {url!r}"

    def test_clearance_observer_not_lambda_none(self) -> None:
        """clearance_getter must not be the anonymous lambda: None stub."""
        with (
            patch("cli.main.EnvTargetProvider"),
            patch("cli.main.EnvBrowserParameterProvider"),
            patch("cli.main.EnvTokenProvider"),
            patch("cli.main.GhCICheckProvider"),
            patch("cli.main.RealWorkServerLifecycle"),
            patch("cli.main.LabelTargetValidator"),
            patch("cli.main.RealBrowserLauncher"),
            patch("cli.main.RealClearanceObserver") as m_observer,
            patch("cli.main.RealClearancePostClient"),
            patch("cli.main.RealClearanceProviders"),
            patch("cli.main.RealClearanceSeams"),
            patch("cli.main.RealClearanceHarness") as m_harness_cls,
        ):
            mock_report = HarnessReport(status=HarnessStatus.PASS)
            m_harness_cls.return_value.run.return_value = mock_report
            runner.invoke(app, ["smoke-clearance", "--real-clearance"])
            obs_kwargs = m_observer.call_args.kwargs if m_observer.call_args else {}
            getter = obs_kwargs.get("clearance_getter")
            assert getter is not None, "clearance_getter must be provided"
            assert callable(getter)
            assert getter.__name__ != "<lambda>", (
                "clearance_getter must not be an anonymous lambda; "
                "use a named closure from _make_clearance_getter"
            )

    def test_clearance_getter_behavioral_sends_request_to_correct_url(self) -> None:
        """Behavioral: recorder must receive a Request to the correct URL.

        Verifies URL and Authorization header — no network involved.
        """
        from cli.main import _make_clearance_getter

        _URL = "http://127.0.0.1:9731/api/clearance/latest"
        captured: list[urllib.request.Request] = []

        def _recorder(req: urllib.request.Request) -> object:
            captured.append(req)
            raise ConnectionRefusedError("mock — no network")

        getter = _make_clearance_getter(_URL, "test-token", getter=_recorder)
        try:
            getter()
        except ConnectionError:
            pass

        assert len(captured) == 1, "getter() must call the recorder exactly once"
        req = captured[0]
        assert isinstance(req, urllib.request.Request), (
            f"recorder must receive a urllib.request.Request, got {type(req)}"
        )
        assert req.full_url == _URL, (
            f"Request URL must be {_URL!r}, got {req.full_url!r}"
        )
        auth = req.get_header("Authorization")
        assert auth == "Bearer test-token", (
            f"Authorization header must be 'Bearer test-token', got {auth!r}"
        )

    def test_clearance_getter_token_reaches_closure(self) -> None:
        """Behavioral: token must be captured in closure and sent as Bearer auth."""
        from cli.main import _make_clearance_getter

        _URL = "http://127.0.0.1:9731/api/clearance/latest"
        captured: list[urllib.request.Request] = []

        def _recorder(req: urllib.request.Request) -> object:
            captured.append(req)
            raise ConnectionRefusedError("mock — no network")

        getter = _make_clearance_getter(_URL, "secret-token-abc", getter=_recorder)
        try:
            getter()
        except ConnectionError:
            pass

        assert len(captured) == 1
        req = captured[0]
        auth = req.get_header("Authorization")
        assert auth == "Bearer secret-token-abc", (
            f"Token must be captured in closure and sent as Bearer, got {auth!r}"
        )


class TestMakeClearanceGetter:
    """Unit tests for the _make_clearance_getter factory."""

    def test_returns_none_on_204(self) -> None:
        from cli.main import _make_clearance_getter

        _URL = "http://127.0.0.1:9731/api/clearance/latest"
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: mock_resp
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.status = 204
        getter = _make_clearance_getter(_URL, "tok", getter=lambda req: mock_resp)
        result = getter()
        assert result is None

    def test_returns_clearance_result_on_200(self) -> None:
        import json
        from datetime import UTC, datetime, timedelta

        from cli.main import _make_clearance_getter
        from cli.smoke_clearance_real import ClearanceResult

        _URL = "http://127.0.0.1:9731/api/clearance/latest"
        expires = (
            (datetime.now(UTC) + timedelta(minutes=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        )
        body = json.dumps(
            {"expires_at": expires, "clearance_class": "cf_clearance@fbref.com"}
        ).encode()
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: mock_resp
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.status = 200
        mock_resp.read.return_value = body
        getter = _make_clearance_getter(_URL, "tok", getter=lambda req: mock_resp)
        result = getter()
        assert isinstance(result, ClearanceResult)
        assert result.obtained is True

    def test_raises_connection_error_on_transport_failure(self) -> None:
        import pytest

        from cli.main import _make_clearance_getter

        _URL = "http://127.0.0.1:9731/api/clearance/latest"

        def _raise(req: object) -> object:
            raise ConnectionRefusedError("no server")

        getter = _make_clearance_getter(_URL, "tok", getter=_raise)
        with pytest.raises(ConnectionError):
            getter()

    def test_no_network_call_in_tests(self) -> None:
        """Verify getter is injectable — passing a mock never hits real network."""
        from cli.main import _make_clearance_getter

        _URL = "http://127.0.0.1:9731/api/clearance/latest"
        calls: list[object] = []

        def _recorder(req: object) -> object:
            calls.append(req)
            raise ConnectionRefusedError("mock")
        getter = _make_clearance_getter(_URL, "tok", getter=_recorder)
        try:
            getter()
        except ConnectionError:
            pass
        assert len(calls) == 1

    def test_raises_connection_error_on_oserror(self) -> None:
        import pytest

        from cli.main import _make_clearance_getter

        _URL = "http://127.0.0.1:9731/api/clearance/latest"

        def _raise(req: object) -> object:
            raise OSError("network failure")

        getter = _make_clearance_getter(_URL, "tok", getter=_raise)
        with pytest.raises(ConnectionError):
            getter()

    def test_raises_connection_error_on_urlerror(self) -> None:
        import urllib.error

        import pytest

        from cli.main import _make_clearance_getter

        _URL = "http://127.0.0.1:9731/api/clearance/latest"

        def _raise(req: object) -> object:
            raise urllib.error.URLError("network error")

        getter = _make_clearance_getter(_URL, "tok", getter=_raise)
        with pytest.raises(ConnectionError):
            getter()

    def test_raises_connection_error_when_enter_raises_oserror(self) -> None:
        import pytest

        from cli.main import _make_clearance_getter

        _URL = "http://127.0.0.1:9731/api/clearance/latest"

        class _RaisesOnEnter:
            def __enter__(self) -> object:
                raise OSError("socket error on enter")

            def __exit__(self, *args: object) -> bool:
                return False

        getter = _make_clearance_getter(
            _URL, "tok", getter=lambda req: _RaisesOnEnter()  # noqa: ARG005
        )
        with pytest.raises(ConnectionError):
            getter()

    def test_raises_connection_error_when_enter_raises_urlerror(self) -> None:
        import urllib.error

        import pytest

        from cli.main import _make_clearance_getter

        _URL = "http://127.0.0.1:9731/api/clearance/latest"

        class _RaisesOnEnter:
            def __enter__(self) -> object:
                raise urllib.error.URLError("network error on enter")

            def __exit__(self, *args: object) -> bool:
                return False

        getter = _make_clearance_getter(
            _URL, "tok", getter=lambda req: _RaisesOnEnter()  # noqa: ARG005
        )
        with pytest.raises(ConnectionError):
            getter()

    def test_returns_none_on_500_with_json_body(self) -> None:
        """A 500 response with a valid JSON body must still return None."""
        import json
        from datetime import UTC, datetime, timedelta

        from cli.main import _make_clearance_getter

        _URL = "http://127.0.0.1:9731/api/clearance/latest"
        expires = (datetime.now(UTC) + timedelta(minutes=2)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        body = json.dumps(
            {"expires_at": expires, "clearance_class": "cf_clearance@fbref.com"}
        ).encode()
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: mock_resp
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.status = 500
        mock_resp.read.return_value = body
        getter = _make_clearance_getter(_URL, "tok", getter=lambda req: mock_resp)
        result = getter()
        assert result is None, (
            f"Expected None on 500 even with valid JSON, got {result!r}"
        )

    def test_returns_none_on_503(self) -> None:
        """Non-200/non-204 response (503) must return None."""
        from cli.main import _make_clearance_getter

        _URL = "http://127.0.0.1:9731/api/clearance/latest"
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: mock_resp
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.status = 503
        getter = _make_clearance_getter(_URL, "tok", getter=lambda req: mock_resp)
        result = getter()
        assert result is None, f"Expected None on 503, got {result!r}"


# ---------------------------------------------------------------------------
# B2: GhCICheckProvider workflow_name wireup
# ---------------------------------------------------------------------------


class TestGhCICheckProviderWorkflowNameWireup:
    def test_gh_ci_check_provider_workflow_name_is_ci(self) -> None:
        _, mocks, _ = _invoke_patched()
        call_kwargs = mocks["ci"].call_args
        assert call_kwargs is not None, "GhCICheckProvider was not called"
        # Accept both positional and keyword argument
        kwargs = call_kwargs.kwargs
        msg = (
            f"GhCICheckProvider must be called with workflow_name='CI',"
            f" got: {call_kwargs!r}"
        )
        assert kwargs.get("workflow_name") == "CI", msg


# ---------------------------------------------------------------------------
# C1: _make_clearance_getter auth error handling
# ---------------------------------------------------------------------------


class TestMakeClearanceGetterAuthErrors:
    _URL = "http://127.0.0.1:9731/api/clearance/latest"

    def _http_error(self, code: int):
        return urllib.error.HTTPError(
            self._URL, code, "Error", http.client.HTTPMessage(), io.BytesIO(b"")
        )

    def test_401_raises_permission_error(self) -> None:
        import pytest

        from cli.main import _make_clearance_getter

        err = self._http_error(401)
        _throw = lambda req: (_ for _ in ()).throw(err)  # noqa: E731
        getter = _make_clearance_getter(self._URL, "secret-token", getter=_throw)
        with pytest.raises(PermissionError):
            getter()

    def test_403_raises_permission_error(self) -> None:
        import pytest

        from cli.main import _make_clearance_getter

        err = self._http_error(403)
        _throw = lambda req: (_ for _ in ()).throw(err)  # noqa: E731
        getter = _make_clearance_getter(self._URL, "secret-token", getter=_throw)
        with pytest.raises(PermissionError):
            getter()

    def test_500_returns_none(self) -> None:
        from cli.main import _make_clearance_getter

        err = self._http_error(500)
        _throw = lambda req: (_ for _ in ()).throw(err)  # noqa: E731
        getter = _make_clearance_getter(self._URL, "secret-token", getter=_throw)
        result = getter()
        assert result is None

    def test_missing_expires_at_returns_none(self) -> None:
        from cli.main import _make_clearance_getter

        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: mock_resp
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.status = 200
        mock_resp.read.return_value = b"{}"
        getter = _make_clearance_getter(
            self._URL, "secret-token", getter=lambda req: mock_resp  # noqa: ARG005
        )
        result = getter()
        assert result is None

    def test_malformed_date_returns_none(self) -> None:
        import json as _json

        from cli.main import _make_clearance_getter

        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: mock_resp
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.status = 200
        mock_resp.read.return_value = _json.dumps({"expires_at": "not-a-date"}).encode()
        getter = _make_clearance_getter(
            self._URL, "secret-token", getter=lambda req: mock_resp
        )
        result = getter()
        assert result is None


# ---------------------------------------------------------------------------
# Browser engine wiring tests
# ---------------------------------------------------------------------------


class _FakeEngine:
    """Minimal fake PydollEngine — records async calls without touching Chrome."""

    def __init__(self, **kwargs: object) -> None:
        self.init_kwargs = kwargs
        self.start_calls: int = 0
        self.execute_script_args: list[str] = []
        self.close_calls: int = 0

    async def start(self) -> None:
        self.start_calls += 1

    async def execute_script(self, script: str) -> None:
        self.execute_script_args.append(script)

    async def close(self) -> None:
        self.close_calls += 1


def _invoke_patched_with_engine(
    fake_engine: _FakeEngine,
    harness_status: HarnessStatus = HarnessStatus.PASS,
) -> tuple[object, MagicMock, MagicMock]:
    """Invoke --real-clearance patching PydollEngine to return *fake_engine*.

    Returns (result, launcher_mock, harness_inst).
    """
    mock_report = HarnessReport(status=harness_status)

    with (
        patch("cli.main.PydollEngine", return_value=fake_engine) as m_engine_cls,
        patch("cli.main.EnvTargetProvider"),
        patch("cli.main.EnvBrowserParameterProvider"),
        patch("cli.main.EnvTokenProvider"),
        patch("cli.main.GhCICheckProvider"),
        patch("cli.main.RealWorkServerLifecycle"),
        patch("cli.main.LabelTargetValidator"),
        patch("cli.main.RealBrowserLauncher") as m_launcher,
        patch("cli.main.RealClearanceObserver"),
        patch("cli.main.RealClearancePostClient"),
        patch("cli.main.RealClearanceProviders"),
        patch("cli.main.RealClearanceSeams"),
        patch("cli.main.RealClearanceHarness") as m_harness_cls,
    ):
        mock_harness_inst = MagicMock()
        mock_harness_inst.run.return_value = mock_report
        m_harness_cls.return_value = mock_harness_inst

        runner.invoke(app, ["smoke-clearance", "--real-clearance"])
        return m_engine_cls, m_launcher, mock_harness_inst


class TestBrowserEngineWiring:
    """PydollEngine must be constructed and wired into RealBrowserLauncher."""

    def test_pydoll_engine_constructed_with_profile_dir_from_settings(self) -> None:
        """PydollEngine must receive profile_dir from settings.scraping."""
        from config.settings import Settings

        _s = Settings()  # type: ignore[call-arg]
        expected_profile = _s.scraping.chrome_profile_dir
        fake_engine = _FakeEngine()
        m_engine_cls, _, _ = _invoke_patched_with_engine(fake_engine)
        call_kwargs = m_engine_cls.call_args  # type: ignore[union-attr]
        assert call_kwargs is not None, "PydollEngine was not constructed"
        profile_dir = call_kwargs.kwargs.get("profile_dir")
        assert profile_dir == expected_profile, (
            f"PydollEngine must receive profile_dir={expected_profile!r},"
            f" got {profile_dir!r}"
        )

    def test_pydoll_engine_constructed_with_name_smoke_clearance(self) -> None:
        """PydollEngine must receive name='smoke-clearance'."""
        fake_engine = _FakeEngine()
        m_engine_cls, _, _ = _invoke_patched_with_engine(fake_engine)
        call_kwargs = m_engine_cls.call_args  # type: ignore[union-attr]
        assert call_kwargs is not None, "PydollEngine was not constructed"
        name = call_kwargs.kwargs.get("name")
        assert name == "smoke-clearance", (
            f"PydollEngine must receive name='smoke-clearance', got {name!r}"
        )

    def test_engine_starter_closure_delegates_to_engine_start(self) -> None:
        """engine_starter coroutine must call engine.start() exactly once."""
        import asyncio

        fake_engine = _FakeEngine()
        _, m_launcher, _ = _invoke_patched_with_engine(fake_engine)
        call_kwargs = m_launcher.call_args
        assert call_kwargs is not None, "RealBrowserLauncher was not constructed"
        engine_starter = call_kwargs.kwargs.get("engine_starter")
        assert engine_starter is not None, "engine_starter must be provided"
        assert asyncio.iscoroutinefunction(engine_starter), (
            "engine_starter must be an async callable"
        )
        asyncio.run(engine_starter())
        assert fake_engine.start_calls == 1, (
            f"engine.start() must be called once via engine_starter, "
            f"got {fake_engine.start_calls}"
        )

    def test_cdp_probe_closure_delegates_to_engine_execute_script_1(self) -> None:
        """cdp_probe coroutine must call engine.execute_script('1') exactly once."""
        import asyncio

        fake_engine = _FakeEngine()
        _, m_launcher, _ = _invoke_patched_with_engine(fake_engine)
        call_kwargs = m_launcher.call_args
        assert call_kwargs is not None
        cdp_probe = call_kwargs.kwargs.get("cdp_probe")
        assert cdp_probe is not None, "cdp_probe must be provided"
        assert asyncio.iscoroutinefunction(cdp_probe), (
            "cdp_probe must be an async callable"
        )
        asyncio.run(cdp_probe())
        assert fake_engine.execute_script_args == ["1"], (
            f"cdp_probe must call engine.execute_script('1'), "
            f"got {fake_engine.execute_script_args!r}"
        )

    def test_engine_stopper_closure_delegates_to_engine_close(self) -> None:
        """engine_stopper coroutine must call engine.close() exactly once."""
        import asyncio

        fake_engine = _FakeEngine()
        _, m_launcher, _ = _invoke_patched_with_engine(fake_engine)
        call_kwargs = m_launcher.call_args
        assert call_kwargs is not None
        engine_stopper = call_kwargs.kwargs.get("engine_stopper")
        assert engine_stopper is not None, "engine_stopper must be provided"
        assert asyncio.iscoroutinefunction(engine_stopper), (
            "engine_stopper must be an async callable"
        )
        asyncio.run(engine_stopper())
        assert fake_engine.close_calls == 1, (
            f"engine.close() must be called once via engine_stopper, "
            f"got {fake_engine.close_calls}"
        )

    def test_no_noop_engine_starter_in_source(self) -> None:
        """_noop_engine_starter must not appear in cli/main.py source."""
        src = _src()
        assert "_noop_engine_starter" not in src, (
            "_noop_engine_starter stub must be removed from cli/main.py"
        )

    def test_no_noop_cdp_probe_in_source(self) -> None:
        """_noop_cdp_probe must not appear in cli/main.py source."""
        src = _src()
        assert "_noop_cdp_probe" not in src, (
            "_noop_cdp_probe stub must be removed from cli/main.py"
        )

    def test_no_fbref_literal_in_real_clearance_block(self) -> None:
        """'fbref' must not appear in the real_clearance branch of cli/main.py.

        The scrape-players command legitimately contains FBRef literals.
        This test ensures the real-clearance composition block stays generic.
        """
        src = _src()
        marker = "if real_clearance:"
        idx = src.find(marker)
        assert idx != -1, f"Could not find '{marker}' in cli/main.py"
        # Find the next top-level terminator at 4-space indent after the block.
        terminators = [
            src.find(t, idx + len(marker))
            for t in ("\n    if ", "\n    return", "\n    raise")
        ]
        end = min(pos for pos in terminators if pos != -1)
        block = src[idx:end]
        assert len(block) > 0, (
            "real_clearance block extraction returned empty — terminator logic is wrong"
        )
        assert "fbref" not in block.lower(), (
            "'fbref' literal must not appear in the real_clearance block of cli/main.py"
        )


# ---------------------------------------------------------------------------
# Browser engine init failure
# ---------------------------------------------------------------------------


class TestBrowserEngineInitFailure:
    def test_engine_init_failure_exits_1(self) -> None:
        """If PydollEngine.__init__ raises, exit code must be 1 — not unhandled."""
        echo_mock = MagicMock()
        with (
            patch("cli.main.PydollEngine", side_effect=RuntimeError("bad profile")),
            patch("cli.main.Settings"),
            patch("cli.main.typer.echo", echo_mock),
        ):
            result = runner.invoke(app, ["smoke-clearance", "--real-clearance"])
        assert result.exit_code == 1, (
            f"Expected exit 1 when PydollEngine init fails, got {result.exit_code}"
        )
        diagnostic_calls = [
            c
            for c in echo_mock.call_args_list
            if c.kwargs.get("err") is True
            and "browser engine init failed" in str(c.args[0] if c.args else "")
        ]
        assert diagnostic_calls, (
            f"Expected typer.echo with 'browser engine init failed' and err=True, "
            f"got calls: {echo_mock.call_args_list!r}"
        )
