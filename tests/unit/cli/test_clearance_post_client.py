"""Unit tests for RealClearancePostClient.

Covers two test surfaces:
- Client unit tests: URL, headers, payload shape, timestamps, return values,
  secret safety, and unknown-label error handling. All tests are fully synthetic
  (injectable poster mock; no real server, network, browser, or cookie values).
- Harness integration (gate 14): verifies that RealClearanceHarness correctly
  blocks on non-204 status or non-zero body bytes, and passes on (204, 0).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

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

_FAKE_URL = "http://127.0.0.1:9999/api/clearance"
_FAKE_TOKEN = "test-bearer-token"
_KNOWN_LABEL = "cf_clearance@fbref.com"
_PLACEHOLDER_CLEARANCE = "__smoke_probe_clearance__"
_SYNTHETIC_PROFILE_ID = "__smoke__"
_SYNTHETIC_WORKER_ID = "__smoke__"


def _fixed_clock(dt: datetime | None = None) -> Any:
    fixed = dt or datetime(2026, 8, 26, 12, 0, 0, tzinfo=UTC)
    return lambda: fixed


def _parse_body(poster: Any) -> dict[str, str]:
    """Extract and parse the JSON body bytes from a mock poster call."""
    body_bytes: bytes = poster.call_args[0][2]
    return json.loads(body_bytes)


def _make_client(
    *,
    url: str = _FAKE_URL,
    token: str = _FAKE_TOKEN,
    poster: Any = None,
    clock: Any = None,
) -> Any:
    from cli.clearance_post_client import RealClearancePostClient

    kwargs: dict[str, Any] = {"url": url, "token": token}
    if poster is not None:
        kwargs["poster"] = poster
    if clock is not None:
        kwargs["clock"] = clock
    return RealClearancePostClient(**kwargs)


# ---------------------------------------------------------------------------
# Poster receives correct URL
# ---------------------------------------------------------------------------


class TestPostURL:
    def test_poster_called_with_correct_url(self) -> None:
        poster = MagicMock(return_value=(204, 0))
        client = _make_client(url=_FAKE_URL, poster=poster)
        client.post(_KNOWN_LABEL)
        args = poster.call_args
        assert args[0][0] == _FAKE_URL

    def test_poster_called_once(self) -> None:
        poster = MagicMock(return_value=(204, 0))
        client = _make_client(poster=poster)
        client.post(_KNOWN_LABEL)
        poster.assert_called_once()


# ---------------------------------------------------------------------------
# Poster receives correct headers
# ---------------------------------------------------------------------------


class TestPostHeaders:
    def test_content_type_is_application_json(self) -> None:
        poster = MagicMock(return_value=(204, 0))
        client = _make_client(poster=poster)
        client.post(_KNOWN_LABEL)
        headers: dict[str, str] = poster.call_args[0][1]
        assert headers.get("Content-Type") == "application/json"

    def test_authorization_header_is_bearer_token(self) -> None:
        poster = MagicMock(return_value=(204, 0))
        client = _make_client(token=_FAKE_TOKEN, poster=poster)
        client.post(_KNOWN_LABEL)
        headers: dict[str, str] = poster.call_args[0][1]
        assert headers.get("Authorization") == f"Bearer {_FAKE_TOKEN}"

    def test_token_is_not_in_body(self) -> None:
        poster = MagicMock(return_value=(204, 0))
        client = _make_client(token=_FAKE_TOKEN, poster=poster)
        client.post(_KNOWN_LABEL)
        body_bytes: bytes = poster.call_args[0][2]
        body_str = body_bytes.decode()
        assert _FAKE_TOKEN not in body_str


# ---------------------------------------------------------------------------
# Payload shape
# ---------------------------------------------------------------------------


class TestPostPayloadShape:
    def test_body_has_exactly_six_required_keys(self) -> None:
        poster = MagicMock(return_value=(204, 0))
        client = _make_client(poster=poster)
        client.post(_KNOWN_LABEL)
        body = _parse_body(poster)
        assert set(body.keys()) == {
            "domain",
            "profile_id",
            "worker_id",
            "observed_at",
            "expires_at",
            "clearance",
        }

    def test_known_label_maps_to_dot_fbref_domain(self) -> None:
        poster = MagicMock(return_value=(204, 0))
        client = _make_client(poster=poster)
        client.post(_KNOWN_LABEL)
        body = _parse_body(poster)
        assert body["domain"] == ".fbref.com"

    def test_clearance_field_is_placeholder_not_label(self) -> None:
        poster = MagicMock(return_value=(204, 0))
        client = _make_client(poster=poster)
        client.post(_KNOWN_LABEL)
        body = _parse_body(poster)
        assert body["clearance"] != _KNOWN_LABEL
        assert body["clearance"] == _PLACEHOLDER_CLEARANCE

    def test_profile_id_is_synthetic(self) -> None:
        poster = MagicMock(return_value=(204, 0))
        client = _make_client(poster=poster)
        client.post(_KNOWN_LABEL)
        body = _parse_body(poster)
        assert body["profile_id"] == _SYNTHETIC_PROFILE_ID

    def test_worker_id_is_synthetic(self) -> None:
        poster = MagicMock(return_value=(204, 0))
        client = _make_client(poster=poster)
        client.post(_KNOWN_LABEL)
        body = _parse_body(poster)
        assert body["worker_id"] == _SYNTHETIC_WORKER_ID

    def test_all_payload_values_are_strings(self) -> None:
        poster = MagicMock(return_value=(204, 0))
        client = _make_client(poster=poster)
        client.post(_KNOWN_LABEL)
        body = _parse_body(poster)
        for key, val in body.items():
            assert isinstance(val, str), f"field {key!r} is not a string: {val!r}"


# ---------------------------------------------------------------------------
# Timestamp determinism and ordering
# ---------------------------------------------------------------------------


class TestPostTimestamps:
    def test_observed_at_less_than_expires_at(self) -> None:
        poster = MagicMock(return_value=(204, 0))
        client = _make_client(poster=poster)
        client.post(_KNOWN_LABEL)
        body = _parse_body(poster)
        obs = datetime.fromisoformat(body["observed_at"].replace("Z", "+00:00"))
        exp = datetime.fromisoformat(body["expires_at"].replace("Z", "+00:00"))
        assert obs < exp

    def test_expires_at_greater_than_observed_at_by_one_minute(self) -> None:
        fixed = datetime(2026, 8, 26, 12, 0, 0, tzinfo=UTC)
        poster = MagicMock(return_value=(204, 0))
        client = _make_client(poster=poster, clock=_fixed_clock(fixed))
        client.post(_KNOWN_LABEL)
        body = _parse_body(poster)
        obs = datetime.fromisoformat(body["observed_at"].replace("Z", "+00:00"))
        exp = datetime.fromisoformat(body["expires_at"].replace("Z", "+00:00"))
        assert (exp - obs).total_seconds() == 60

    def test_observed_at_uses_injected_clock(self) -> None:
        fixed = datetime(2026, 8, 26, 15, 30, 0, tzinfo=UTC)
        poster = MagicMock(return_value=(204, 0))
        client = _make_client(poster=poster, clock=_fixed_clock(fixed))
        client.post(_KNOWN_LABEL)
        body = _parse_body(poster)
        obs = datetime.fromisoformat(body["observed_at"].replace("Z", "+00:00"))
        assert obs == fixed

    def test_observed_at_is_valid_utc_iso8601(self) -> None:
        poster = MagicMock(return_value=(204, 0))
        client = _make_client(poster=poster)
        client.post(_KNOWN_LABEL)
        body = _parse_body(poster)
        dt = datetime.fromisoformat(body["observed_at"].replace("Z", "+00:00"))
        assert dt.tzinfo is not None

    def test_expires_at_is_valid_utc_iso8601(self) -> None:
        poster = MagicMock(return_value=(204, 0))
        client = _make_client(poster=poster)
        client.post(_KNOWN_LABEL)
        body = _parse_body(poster)
        dt = datetime.fromisoformat(body["expires_at"].replace("Z", "+00:00"))
        assert dt.tzinfo is not None


# ---------------------------------------------------------------------------
# Return values
# ---------------------------------------------------------------------------


class TestPostReturnValues:
    def test_returns_204_and_zero_on_success(self) -> None:
        poster = MagicMock(return_value=(204, 0))
        client = _make_client(poster=poster)
        status, body_bytes = client.post(_KNOWN_LABEL)
        assert status == 204
        assert body_bytes == 0

    def test_returns_500_status_unchanged(self) -> None:
        poster = MagicMock(return_value=(500, 5))
        client = _make_client(poster=poster)
        status, body_bytes = client.post(_KNOWN_LABEL)
        assert status == 500
        assert body_bytes == 5

    def test_returns_401_status_unchanged(self) -> None:
        poster = MagicMock(return_value=(401, 0))
        client = _make_client(poster=poster)
        status, _ = client.post(_KNOWN_LABEL)
        assert status == 401

    def test_non_zero_body_bytes_returned_unchanged(self) -> None:
        poster = MagicMock(return_value=(204, 42))
        client = _make_client(poster=poster)
        _, body_bytes = client.post(_KNOWN_LABEL)
        assert body_bytes == 42


# ---------------------------------------------------------------------------
# Secret safety
# ---------------------------------------------------------------------------


class TestSecretSafety:
    def test_no_payload_value_is_sensitive(self) -> None:
        poster = MagicMock(return_value=(204, 0))
        client = _make_client(poster=poster)
        client.post(_KNOWN_LABEL)
        body = _parse_body(poster)
        for key, val in body.items():
            assert not scan_for_sensitive(str(val)), (
                f"Sensitive material found in payload field {key!r}"
            )

    def test_clearance_class_label_not_sensitive(self) -> None:
        assert not scan_for_sensitive(_KNOWN_LABEL)

    def test_placeholder_clearance_not_sensitive(self) -> None:
        assert not scan_for_sensitive(_PLACEHOLDER_CLEARANCE)


# ---------------------------------------------------------------------------
# Unknown clearance class
# ---------------------------------------------------------------------------


class TestUnknownClearanceClass:
    def test_unknown_label_raises_value_error(self) -> None:
        import pytest

        poster = MagicMock(return_value=(204, 0))
        client = _make_client(poster=poster)
        with pytest.raises(ValueError):
            client.post("cf_clearance@unknown.com")

    def test_empty_label_raises_value_error(self) -> None:
        import pytest

        poster = MagicMock(return_value=(204, 0))
        client = _make_client(poster=poster)
        with pytest.raises(ValueError):
            client.post("")


# ---------------------------------------------------------------------------
# Harness fake stubs (re-used across gate tests)
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

    def validate_against_allowlist(self, _allowlist: frozenset[str]) -> bool:
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
    def validate(self, _target_class: str) -> Any:
        from cli.smoke_clearance_real import ValidationResult

        return ValidationResult.VALID


class _FakeWorkServer:
    def startup(self, timeout_s: int) -> None:
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

    def wait_cdp_ready(self, timeout_s: int) -> tuple[bool, int]:
        return True, 1


class _FakeClearanceObserver:
    def observe(self, timeout_s: int) -> ClearanceResult:
        return ClearanceResult(
            obtained=True,
            expires_at=datetime.now(UTC) + timedelta(minutes=2),
            clearance_class=_KNOWN_LABEL,
        )


def _make_providers() -> RealClearanceProviders:
    return RealClearanceProviders(
        target=_FakeTargetProvider(),  # type: ignore[arg-type]
        browser_params=_FakeBrowserParamProvider(),  # type: ignore[arg-type]
        token=_FakeTokenProvider(),  # type: ignore[arg-type]
    )


def _make_seams(post_client: Any) -> RealClearanceSeams:
    return RealClearanceSeams(
        ci_check=_FakeCICheck(),  # type: ignore[arg-type]
        work_server=_FakeWorkServer(),  # type: ignore[arg-type]
        target_validator=_FakeTargetValidator(),  # type: ignore[arg-type]
        browser_launcher=_FakeBrowserLauncher(),  # type: ignore[arg-type]
        clearance_observer=_FakeClearanceObserver(),  # type: ignore[arg-type]
        clearance_post=post_client,  # type: ignore[arg-type]
        resolved_host="127.0.0.1",
    )


# ---------------------------------------------------------------------------
# Harness integration — gate 14
# ---------------------------------------------------------------------------


class TestHarnessGate14:
    def test_gate14_blocks_when_post_status_is_not_204(self) -> None:
        poster = MagicMock(return_value=(500, 0))
        client = _make_client(poster=poster)
        report = RealClearanceHarness().run(_make_providers(), _make_seams(client))
        gate = RealClearanceHarness.GATE_POST_CLEARANCE
        assert report.gate_results.get(gate) == GateStatus.BLOCKED
        assert report.status == HarnessStatus.BLOCKED
        assert report.error_gate == gate

    def test_gate14_blocks_when_body_bytes_nonzero(self) -> None:
        poster = MagicMock(return_value=(204, 42))
        client = _make_client(poster=poster)
        report = RealClearanceHarness().run(_make_providers(), _make_seams(client))
        gate = RealClearanceHarness.GATE_POST_CLEARANCE
        assert report.gate_results.get(gate) == GateStatus.BLOCKED
        assert report.status == HarnessStatus.BLOCKED

    def test_gate14_passes_when_204_and_zero_bytes(self) -> None:
        poster = MagicMock(return_value=(204, 0))
        client = _make_client(poster=poster)
        report = RealClearanceHarness().run(_make_providers(), _make_seams(client))
        gate = RealClearanceHarness.GATE_POST_CLEARANCE
        assert report.gate_results.get(gate) == GateStatus.PASS
        assert report.status == HarnessStatus.PASS
