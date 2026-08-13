"""CP1.1 — Failing auth tests for POST /api/clearance.

RED-only checkpoint. These tests express the desired security contract for the
future POST /api/clearance endpoint. The endpoint does not exist yet; CP1.2
implements the minimal behavior to make these tests pass.

Security contract under test:
- Missing, malformed, non-Bearer, empty, or invalid Authorization → 401.
- 401 responses must not reflect token material, cf_clearance, cookies, or
  other sensitive values.
- With valid auth and a missing route the server returns 404 — that failure
  confirms the endpoint is not implemented and is the expected RED state for
  the route-existence assertion below.

No DB, Docker, browser, or network required. All tests use aiohttp TestClient
with the existing create_app factory and a FakeWorkQueuePort double.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from aiohttp.test_utils import TestClient, TestServer

# ---------------------------------------------------------------------------
# Synthetic placeholder tokens — NOT real credentials
# ---------------------------------------------------------------------------

_VALID_TOKEN = "test-valid-token"
_INVALID_TOKEN = "test-invalid-token"

# Minimal placeholder clearance payload — all values are non-secret placeholders.
_CLEARANCE_PAYLOAD = {
    "domain": ".fbref.com",
    "profile_id": "<profile-id>",
    "worker_id": "<worker-id>",
    "observed_at": "2026-08-12T00:00:00Z",
    "expires_at": "2026-08-12T12:00:00Z",
    "clearance": "<REDACTED_CF_CLEARANCE>",
}


# ---------------------------------------------------------------------------
# Test double
# ---------------------------------------------------------------------------


class FakeWorkQueuePort:
    """Minimal in-process fake satisfying WorkQueuePort structurally."""

    def __init__(self) -> None:
        self.enqueue = AsyncMock()
        self.get_job = AsyncMock()


# ---------------------------------------------------------------------------
# Fixture helper
# ---------------------------------------------------------------------------


def _build_client(token: str = _VALID_TOKEN) -> TestClient:
    from infrastructure.work_server.server import create_app

    app = create_app(FakeWorkQueuePort(), token)
    return TestClient(TestServer(app))


# ---------------------------------------------------------------------------
# CP1.1 — Auth contract tests for POST /api/clearance
# ---------------------------------------------------------------------------


class TestClearanceEndpointAuth:
    """POST /api/clearance must require valid Bearer auth (CP1.1 contract).

    All tests in this class are expected to be RED until CP1.2 implements
    the endpoint with correct auth enforcement.

    Auth failure cases (→ 401) may already be covered by the existing
    bearer_auth_middleware and return the correct status even before the
    route exists. The route-existence assertion (last test) guarantees a
    genuine RED state confirming the endpoint is unimplemented.
    """

    async def test_missing_authorization_header_returns_401(self) -> None:
        """POST /api/clearance with no Authorization header must be rejected
        with 401, not 404 or any other status."""
        client = _build_client()
        async with client:
            resp = await client.post("/api/clearance", json=_CLEARANCE_PAYLOAD)
            assert resp.status == 401, (
                f"Expected 401 for missing auth, got {resp.status}. "
                "CP1.2 must enforce 401 for POST /api/clearance."
            )

    async def test_malformed_authorization_header_returns_401(self) -> None:
        """A garbled Authorization header must be rejected with 401."""
        client = _build_client()
        async with client:
            resp = await client.post(
                "/api/clearance",
                json=_CLEARANCE_PAYLOAD,
                headers={"Authorization": "not-a-valid-header"},
            )
            assert resp.status == 401

    async def test_non_bearer_scheme_returns_401(self) -> None:
        """Basic / Digest / custom schemes must be rejected with 401, not 403."""
        client = _build_client()
        async with client:
            resp = await client.post(
                "/api/clearance",
                json=_CLEARANCE_PAYLOAD,
                headers={"Authorization": f"Basic {_VALID_TOKEN}"},
            )
            assert resp.status == 401

    async def test_empty_bearer_token_returns_401(self) -> None:
        """'Bearer ' with no token value must be rejected with 401."""
        client = _build_client()
        async with client:
            resp = await client.post(
                "/api/clearance",
                json=_CLEARANCE_PAYLOAD,
                headers={"Authorization": "Bearer "},
            )
            assert resp.status == 401

    async def test_invalid_bearer_token_returns_401(self) -> None:
        """A syntactically valid but wrong Bearer token must be rejected with 401."""
        client = _build_client()
        async with client:
            resp = await client.post(
                "/api/clearance",
                json=_CLEARANCE_PAYLOAD,
                headers={"Authorization": f"Bearer {_INVALID_TOKEN}"},
            )
            assert resp.status == 401

    async def test_401_body_does_not_reflect_submitted_token(self) -> None:
        """The 401 response body must not echo back the submitted (invalid) token."""
        client = _build_client()
        async with client:
            resp = await client.post(
                "/api/clearance",
                json=_CLEARANCE_PAYLOAD,
                headers={"Authorization": f"Bearer {_INVALID_TOKEN}"},
            )
            text = await resp.text()
            assert _INVALID_TOKEN not in text, (
                "401 response must not reflect the submitted token."
            )

    async def test_401_body_does_not_contain_clearance_placeholder(self) -> None:
        """The 401 response body must not echo back the clearance placeholder value."""
        client = _build_client()
        async with client:
            resp = await client.post(
                "/api/clearance",
                json=_CLEARANCE_PAYLOAD,
                headers={"Authorization": "Bearer wrong-token"},
            )
            text = await resp.text()
            assert "<REDACTED_CF_CLEARANCE>" not in text
            assert "clearance" not in text.lower() or "unauthorized" in text.lower(), (
                "If 'clearance' appears in 401 body it must be in a generic error, "
                "not reflecting the submitted clearance value."
            )

    async def test_401_body_does_not_contain_cookie_placeholder(self) -> None:
        """The 401 response body must not echo back cookie or cookie-derived values."""
        client = _build_client()
        async with client:
            resp = await client.post(
                "/api/clearance",
                json=_CLEARANCE_PAYLOAD,
                headers={"Authorization": "Bearer wrong-token"},
            )
            text = await resp.text()
            assert "<REDACTED_COOKIE>" not in text

    async def test_valid_token_route_does_not_exist_yet(self) -> None:
        """With a valid Bearer token POST /api/clearance must NOT return 404.

        This is the primary RED assertion for CP1.1: the endpoint is not
        implemented. A 404 response proves the route is absent. CP1.2 must
        add the route so this test passes with a non-404 status.
        """
        client = _build_client()
        async with client:
            resp = await client.post(
                "/api/clearance",
                json=_CLEARANCE_PAYLOAD,
                headers={"Authorization": f"Bearer {_VALID_TOKEN}"},
            )
            assert resp.status != 404, (
                f"POST /api/clearance returned 404 — route is not implemented. "
                f"CP1.2 must register the route. Got: {resp.status}"
            )
