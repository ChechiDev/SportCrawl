"""CP1.2 — Failing payload validation tests for POST /api/clearance.

RED-only checkpoint. These tests express the desired payload validation
contract for the future POST /api/clearance endpoint. The endpoint does not
exist yet; CP1.3 implements the minimal behavior to make CP1.1 and CP1.2
tests pass.

All tests use valid placeholder Bearer auth so failures exercise payload
validation, not auth. A 404 from a missing route is the expected failure
reason at this point; tests assert specific validation status codes.

No DB, Docker, browser, or network required.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from aiohttp.test_utils import TestClient, TestServer

# ---------------------------------------------------------------------------
# Placeholder credentials — NOT real values
# ---------------------------------------------------------------------------

_VALID_TOKEN = "test-valid-token"
_AUTH = {"Authorization": f"Bearer {_VALID_TOKEN}"}

# A well-formed placeholder payload that should pass validation once CP1.3
# implements the endpoint.
_VALID_PAYLOAD = {
    "domain": ".fbref.com",
    "profile_id": "<profile-id>",
    "worker_id": "<worker-id>",
    "observed_at": "2026-08-12T00:00:00Z",
    "expires_at": "2026-08-12T12:00:00Z",
    "clearance": "<REDACTED_CF_CLEARANCE>",
}

# Oversized clearance string (64 KB + 1 byte) — above any reasonable field limit.
_OVERSIZED_CLEARANCE = "x" * (64 * 1024 + 1)


# ---------------------------------------------------------------------------
# Fake port double
# ---------------------------------------------------------------------------


class FakeWorkQueuePort:
    def __init__(self) -> None:
        self.enqueue = AsyncMock()
        self.get_job = AsyncMock()


# ---------------------------------------------------------------------------
# Fixture helper — identical pattern to test_work_server.py / test_clearance_auth.py
# ---------------------------------------------------------------------------


def _build_client(token: str = _VALID_TOKEN) -> TestClient:
    from infrastructure.work_server.server import create_app

    app = create_app(FakeWorkQueuePort(), token)
    return TestClient(TestServer(app))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _drop(payload: dict, key: str) -> dict:
    """Return a copy of payload with the given key removed."""
    return {k: v for k, v in payload.items() if k != key}


def _replace(payload: dict, key: str, value: object) -> dict:
    """Return a copy of payload with key set to value."""
    return {**payload, key: value}


# ---------------------------------------------------------------------------
# CP1.2 — Payload validation contract tests
# ---------------------------------------------------------------------------


class TestClearancePayloadValidation:
    """POST /api/clearance payload validation contract (CP1.2).

    All tests use a valid Bearer token so that auth is not the reason for
    failure. Expected failure reason: endpoint not implemented (404 today).
    Each test documents the status it expects from a fully-implemented endpoint
    so CP1.3 knows exactly what to satisfy.
    """

    # -----------------------------------------------------------------------
    # 400 — Bad Request (syntactically invalid body)
    # -----------------------------------------------------------------------

    async def test_invalid_json_returns_400(self) -> None:
        """Non-parseable body must be rejected with 400."""
        client = _build_client()
        async with client:
            resp = await client.post(
                "/api/clearance",
                data="not-json{{",
                headers={**_AUTH, "Content-Type": "application/json"},
            )
            assert resp.status == 400, (
                f"Expected 400 for invalid JSON, got {resp.status}. "
                "CP1.3 must implement payload parsing."
            )

    async def test_non_object_json_array_returns_400(self) -> None:
        """A JSON array at the top level must be rejected with 400."""
        client = _build_client()
        async with client:
            resp = await client.post(
                "/api/clearance",
                json=["not", "an", "object"],
                headers=_AUTH,
            )
            assert resp.status == 400, (
                f"Expected 400 for non-object JSON, got {resp.status}."
            )

    async def test_non_object_json_string_returns_400(self) -> None:
        """A JSON string at the top level must be rejected with 400."""
        client = _build_client()
        async with client:
            resp = await client.post(
                "/api/clearance",
                json="just-a-string",
                headers=_AUTH,
            )
            assert resp.status == 400

    async def test_non_object_json_null_returns_400(self) -> None:
        """JSON null body must be rejected with 400."""
        client = _build_client()
        async with client:
            resp = await client.post(
                "/api/clearance",
                data="null",
                headers={**_AUTH, "Content-Type": "application/json"},
            )
            assert resp.status == 400

    # -----------------------------------------------------------------------
    # 415 — Unsupported Media Type
    # -----------------------------------------------------------------------

    async def test_plain_text_content_type_returns_415(self) -> None:
        """Content-Type: text/plain must be rejected with 415."""
        client = _build_client()
        async with client:
            resp = await client.post(
                "/api/clearance",
                data='{"domain": ".fbref.com"}',
                headers={**_AUTH, "Content-Type": "text/plain"},
            )
            assert resp.status == 415, (
                f"Expected 415 for unsupported content type, got {resp.status}."
            )

    async def test_form_encoded_content_type_returns_415(self) -> None:
        """Content-Type: application/x-www-form-urlencoded must be rejected with 415."""
        client = _build_client()
        async with client:
            resp = await client.post(
                "/api/clearance",
                data="domain=.fbref.com",
                headers={**_AUTH, "Content-Type": "application/x-www-form-urlencoded"},
            )
            assert resp.status == 415

    # -----------------------------------------------------------------------
    # 422 — Missing required fields
    # -----------------------------------------------------------------------

    async def test_missing_domain_returns_422(self) -> None:
        client = _build_client()
        async with client:
            resp = await client.post(
                "/api/clearance", json=_drop(_VALID_PAYLOAD, "domain"), headers=_AUTH
            )
            assert resp.status == 422

    async def test_missing_profile_id_returns_422(self) -> None:
        client = _build_client()
        async with client:
            resp = await client.post(
                "/api/clearance",
                json=_drop(_VALID_PAYLOAD, "profile_id"),
                headers=_AUTH,
            )
            assert resp.status == 422

    async def test_missing_worker_id_returns_422(self) -> None:
        client = _build_client()
        async with client:
            resp = await client.post(
                "/api/clearance",
                json=_drop(_VALID_PAYLOAD, "worker_id"),
                headers=_AUTH,
            )
            assert resp.status == 422

    async def test_missing_observed_at_returns_422(self) -> None:
        client = _build_client()
        async with client:
            resp = await client.post(
                "/api/clearance",
                json=_drop(_VALID_PAYLOAD, "observed_at"),
                headers=_AUTH,
            )
            assert resp.status == 422

    async def test_missing_expires_at_returns_422(self) -> None:
        client = _build_client()
        async with client:
            resp = await client.post(
                "/api/clearance",
                json=_drop(_VALID_PAYLOAD, "expires_at"),
                headers=_AUTH,
            )
            assert resp.status == 422

    async def test_missing_clearance_returns_422(self) -> None:
        client = _build_client()
        async with client:
            resp = await client.post(
                "/api/clearance",
                json=_drop(_VALID_PAYLOAD, "clearance"),
                headers=_AUTH,
            )
            assert resp.status == 422

    async def test_empty_object_returns_422(self) -> None:
        """Empty JSON object must be rejected (all required fields missing)."""
        client = _build_client()
        async with client:
            resp = await client.post("/api/clearance", json={}, headers=_AUTH)
            assert resp.status == 422

    # -----------------------------------------------------------------------
    # 422 — Wrong field types
    # -----------------------------------------------------------------------

    async def test_domain_not_string_returns_422(self) -> None:
        client = _build_client()
        async with client:
            resp = await client.post(
                "/api/clearance",
                json=_replace(_VALID_PAYLOAD, "domain", 42),
                headers=_AUTH,
            )
            assert resp.status == 422

    async def test_profile_id_not_string_returns_422(self) -> None:
        client = _build_client()
        async with client:
            resp = await client.post(
                "/api/clearance",
                json=_replace(_VALID_PAYLOAD, "profile_id", ["list"]),
                headers=_AUTH,
            )
            assert resp.status == 422

    async def test_observed_at_not_string_returns_422(self) -> None:
        client = _build_client()
        async with client:
            resp = await client.post(
                "/api/clearance",
                json=_replace(_VALID_PAYLOAD, "observed_at", 1234567890),
                headers=_AUTH,
            )
            assert resp.status == 422

    # -----------------------------------------------------------------------
    # 422 — Domain validation
    # -----------------------------------------------------------------------

    async def test_unsupported_domain_returns_422(self) -> None:
        """A domain not in the allowed-domain list must be rejected with 422."""
        client = _build_client()
        async with client:
            resp = await client.post(
                "/api/clearance",
                json=_replace(_VALID_PAYLOAD, "domain", ".example.com"),
                headers=_AUTH,
            )
            assert resp.status == 422

    async def test_domain_suffix_bypass_returns_422(self) -> None:
        """allowed.com.evil.com must be rejected — suffix match is not enough."""
        client = _build_client()
        async with client:
            resp = await client.post(
                "/api/clearance",
                json=_replace(_VALID_PAYLOAD, "domain", "fbref.com.evil.com"),
                headers=_AUTH,
            )
            assert resp.status == 422

    async def test_domain_path_bypass_returns_422(self) -> None:
        """evil.com/fbref.com path trick must be rejected."""
        client = _build_client()
        async with client:
            resp = await client.post(
                "/api/clearance",
                json=_replace(_VALID_PAYLOAD, "domain", "evil.com/fbref.com"),
                headers=_AUTH,
            )
            assert resp.status == 422

    async def test_domain_userinfo_bypass_returns_422(self) -> None:
        """fbref.com@evil.com userinfo trick must be rejected."""
        client = _build_client()
        async with client:
            resp = await client.post(
                "/api/clearance",
                json=_replace(_VALID_PAYLOAD, "domain", "fbref.com@evil.com"),
                headers=_AUTH,
            )
            assert resp.status == 422

    async def test_loopback_ip_domain_returns_422(self) -> None:
        """127.0.0.1 loopback must be rejected."""
        client = _build_client()
        async with client:
            resp = await client.post(
                "/api/clearance",
                json=_replace(_VALID_PAYLOAD, "domain", "127.0.0.1"),
                headers=_AUTH,
            )
            assert resp.status == 422

    async def test_localhost_domain_returns_422(self) -> None:
        """localhost must be rejected."""
        client = _build_client()
        async with client:
            resp = await client.post(
                "/api/clearance",
                json=_replace(_VALID_PAYLOAD, "domain", "localhost"),
                headers=_AUTH,
            )
            assert resp.status == 422

    async def test_ipv6_loopback_domain_returns_422(self) -> None:
        """[::1] IPv6 loopback must be rejected."""
        client = _build_client()
        async with client:
            resp = await client.post(
                "/api/clearance",
                json=_replace(_VALID_PAYLOAD, "domain", "[::1]"),
                headers=_AUTH,
            )
            assert resp.status == 422

    async def test_empty_domain_returns_422(self) -> None:
        client = _build_client()
        async with client:
            resp = await client.post(
                "/api/clearance",
                json=_replace(_VALID_PAYLOAD, "domain", ""),
                headers=_AUTH,
            )
            assert resp.status == 422

    async def test_domain_with_scheme_returns_422(self) -> None:
        """domain field must not include a URL scheme."""
        client = _build_client()
        async with client:
            resp = await client.post(
                "/api/clearance",
                json=_replace(_VALID_PAYLOAD, "domain", "https://.fbref.com"),
                headers=_AUTH,
            )
            assert resp.status == 422

    async def test_domain_with_query_returns_422(self) -> None:
        """domain field must not include query parameters."""
        client = _build_client()
        async with client:
            resp = await client.post(
                "/api/clearance",
                json=_replace(_VALID_PAYLOAD, "domain", ".fbref.com?x=1"),
                headers=_AUTH,
            )
            assert resp.status == 422

    # -----------------------------------------------------------------------
    # 422 — Timestamp validation
    # -----------------------------------------------------------------------

    async def test_malformed_observed_at_returns_422(self) -> None:
        """Non-ISO-8601 observed_at must be rejected with 422."""
        client = _build_client()
        async with client:
            resp = await client.post(
                "/api/clearance",
                json=_replace(_VALID_PAYLOAD, "observed_at", "not-a-timestamp"),
                headers=_AUTH,
            )
            assert resp.status == 422

    async def test_malformed_expires_at_returns_422(self) -> None:
        """Non-ISO-8601 expires_at must be rejected with 422."""
        client = _build_client()
        async with client:
            resp = await client.post(
                "/api/clearance",
                json=_replace(_VALID_PAYLOAD, "expires_at", "12/31/2026"),
                headers=_AUTH,
            )
            assert resp.status == 422

    async def test_expires_at_equal_to_observed_at_returns_422(self) -> None:
        """expires_at == observed_at must be rejected (clearance already stale)."""
        ts = "2026-08-12T00:00:00Z"
        client = _build_client()
        async with client:
            resp = await client.post(
                "/api/clearance",
                json={**_VALID_PAYLOAD, "observed_at": ts, "expires_at": ts},
                headers=_AUTH,
            )
            assert resp.status == 422

    async def test_expires_at_before_observed_at_returns_422(self) -> None:
        """expires_at < observed_at is a logical impossibility and must be rejected."""
        client = _build_client()
        async with client:
            resp = await client.post(
                "/api/clearance",
                json={
                    **_VALID_PAYLOAD,
                    "observed_at": "2026-08-12T12:00:00Z",
                    "expires_at": "2026-08-12T00:00:00Z",
                },
                headers=_AUTH,
            )
            assert resp.status == 422

    async def test_already_expired_clearance_returns_422(self) -> None:
        """expires_at in the past must be rejected."""
        client = _build_client()
        async with client:
            resp = await client.post(
                "/api/clearance",
                json={
                    **_VALID_PAYLOAD,
                    "observed_at": "2020-01-01T00:00:00Z",
                    "expires_at": "2020-01-01T12:00:00Z",
                },
                headers=_AUTH,
            )
            assert resp.status == 422

    # -----------------------------------------------------------------------
    # 422 — Oversized clearance field
    # -----------------------------------------------------------------------

    async def test_oversized_clearance_field_returns_422(self) -> None:
        """Clearance value exceeding the field size limit must be rejected with 422."""
        client = _build_client()
        async with client:
            resp = await client.post(
                "/api/clearance",
                json=_replace(_VALID_PAYLOAD, "clearance", _OVERSIZED_CLEARANCE),
                headers=_AUTH,
            )
            assert resp.status == 422

    # -----------------------------------------------------------------------
    # 422 — Forbidden extra sensitive fields
    # -----------------------------------------------------------------------

    async def test_extra_cookies_field_returns_422(self) -> None:
        """Payloads with a 'cookies' field must be rejected."""
        client = _build_client()
        async with client:
            resp = await client.post(
                "/api/clearance",
                json={**_VALID_PAYLOAD, "cookies": "<REDACTED_COOKIE>"},
                headers=_AUTH,
            )
            assert resp.status == 422

    async def test_extra_cookie_field_returns_422(self) -> None:
        client = _build_client()
        async with client:
            resp = await client.post(
                "/api/clearance",
                json={**_VALID_PAYLOAD, "cookie": "<REDACTED_COOKIE>"},
                headers=_AUTH,
            )
            assert resp.status == 422

    async def test_extra_headers_field_returns_422(self) -> None:
        client = _build_client()
        async with client:
            resp = await client.post(
                "/api/clearance",
                json={**_VALID_PAYLOAD, "headers": {"x-custom": "value"}},
                headers=_AUTH,
            )
            assert resp.status == 422

    async def test_extra_authorization_field_returns_422(self) -> None:
        client = _build_client()
        async with client:
            resp = await client.post(
                "/api/clearance",
                json={**_VALID_PAYLOAD, "authorization": "<REDACTED_TOKEN>"},
                headers=_AUTH,
            )
            assert resp.status == 422

    async def test_extra_html_field_returns_422(self) -> None:
        client = _build_client()
        async with client:
            resp = await client.post(
                "/api/clearance",
                json={**_VALID_PAYLOAD, "html": "<REDACTED_HTML>"},
                headers=_AUTH,
            )
            assert resp.status == 422

    async def test_extra_profile_path_field_returns_422(self) -> None:
        client = _build_client()
        async with client:
            resp = await client.post(
                "/api/clearance",
                json={**_VALID_PAYLOAD, "profile_path": "<PROFILE_PATH>"},
                headers=_AUTH,
            )
            assert resp.status == 422

    async def test_extra_cdp_state_field_returns_422(self) -> None:
        client = _build_client()
        async with client:
            resp = await client.post(
                "/api/clearance",
                json={**_VALID_PAYLOAD, "cdp_state": {}},
                headers=_AUTH,
            )
            assert resp.status == 422

    async def test_extra_local_storage_field_returns_422(self) -> None:
        client = _build_client()
        async with client:
            resp = await client.post(
                "/api/clearance",
                json={**_VALID_PAYLOAD, "local_storage": {}},
                headers=_AUTH,
            )
            assert resp.status == 422

    async def test_extra_session_storage_field_returns_422(self) -> None:
        client = _build_client()
        async with client:
            resp = await client.post(
                "/api/clearance",
                json={**_VALID_PAYLOAD, "session_storage": {}},
                headers=_AUTH,
            )
            assert resp.status == 422

    async def test_extra_token_field_returns_422(self) -> None:
        client = _build_client()
        async with client:
            resp = await client.post(
                "/api/clearance",
                json={**_VALID_PAYLOAD, "token": "<REDACTED_TOKEN>"},
                headers=_AUTH,
            )
            assert resp.status == 422

    # -----------------------------------------------------------------------
    # Generic error response — no secret echo
    # -----------------------------------------------------------------------

    async def test_validation_error_response_does_not_echo_clearance(self) -> None:
        """Error response must not reflect the submitted clearance value."""
        client = _build_client()
        async with client:
            resp = await client.post(
                "/api/clearance",
                json=_drop(_VALID_PAYLOAD, "domain"),
                headers=_AUTH,
            )
            text = await resp.text()
            assert "<REDACTED_CF_CLEARANCE>" not in text

    async def test_validation_error_response_does_not_echo_token(self) -> None:
        """Error response must not reflect the Bearer token value."""
        client = _build_client()
        async with client:
            resp = await client.post(
                "/api/clearance",
                json=_drop(_VALID_PAYLOAD, "domain"),
                headers=_AUTH,
            )
            text = await resp.text()
            assert _VALID_TOKEN not in text

    async def test_validation_error_response_does_not_echo_cookie_placeholder(
        self,
    ) -> None:
        """Error response for forbidden cookies field must not echo cookie value."""
        client = _build_client()
        async with client:
            resp = await client.post(
                "/api/clearance",
                json={**_VALID_PAYLOAD, "cookies": "<REDACTED_COOKIE>"},
                headers=_AUTH,
            )
            text = await resp.text()
            assert "<REDACTED_COOKIE>" not in text
