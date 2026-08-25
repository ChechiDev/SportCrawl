"""Tests for work-server clearance store bridge.

Covers:
- GET /api/clearance/latest requires auth (401 without Bearer token)
- GET /api/clearance/latest returns 204 when no record exists
- Valid POST /api/clearance stores sanitized metadata; GET returns 200 + JSON
- Invalid POST does not update the store; GET still returns 204
- Second valid POST overwrites the store
- GET response never contains raw clearance field

No DB, Docker, browser, real server, or network required.
All tests use aiohttp in-process TestClient with FakeWorkQueuePort.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

from aiohttp.test_utils import TestClient, TestServer

# ---------------------------------------------------------------------------
# Placeholder credentials — NOT real values
# ---------------------------------------------------------------------------

_VALID_TOKEN = "test-valid-token"
_AUTH = {"Authorization": f"Bearer {_VALID_TOKEN}"}


def _valid_payload(
    domain: str = ".fbref.com",
    observed_offset_s: int = -10,
    expires_offset_s: int = 3600,
) -> dict[str, str]:
    """Build a valid clearance payload with future-safe timestamps."""
    now = datetime.now(UTC)
    observed_at = (now + timedelta(seconds=observed_offset_s)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    expires_at = (now + timedelta(seconds=expires_offset_s)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    return {
        "domain": domain,
        "profile_id": "<profile-id>",
        "worker_id": "<worker-id>",
        "observed_at": observed_at,
        "expires_at": expires_at,
        "clearance": "<REDACTED_CF_CLEARANCE>",
    }


# ---------------------------------------------------------------------------
# Test double
# ---------------------------------------------------------------------------


class FakeWorkQueuePort:
    def __init__(self) -> None:
        self.enqueue = AsyncMock()
        self.get_job = AsyncMock()


# ---------------------------------------------------------------------------
# Client factory
# ---------------------------------------------------------------------------


def _build_client(token: str = _VALID_TOKEN) -> TestClient:
    from infrastructure.work_server.server import create_app

    app = create_app(FakeWorkQueuePort(), token)
    return TestClient(TestServer(app))


# ---------------------------------------------------------------------------
# GET /api/clearance/latest — auth
# ---------------------------------------------------------------------------


class TestGetClearanceLatestAuth:
    async def test_no_auth_header_returns_401(self) -> None:
        client = _build_client()
        async with client:
            resp = await client.get("/api/clearance/latest")
            assert resp.status == 401

    async def test_invalid_token_returns_401(self) -> None:
        client = _build_client()
        async with client:
            resp = await client.get(
                "/api/clearance/latest",
                headers={"Authorization": "Bearer wrong-token"},
            )
            assert resp.status == 401

    async def test_valid_token_accepted(self) -> None:
        client = _build_client()
        async with client:
            resp = await client.get("/api/clearance/latest", headers=_AUTH)
            assert resp.status in (200, 204)


# ---------------------------------------------------------------------------
# GET /api/clearance/latest — empty store
# ---------------------------------------------------------------------------


class TestGetClearanceLatestEmpty:
    async def test_returns_204_when_no_record_exists(self) -> None:
        client = _build_client()
        async with client:
            resp = await client.get("/api/clearance/latest", headers=_AUTH)
            assert resp.status == 204

    async def test_204_has_empty_body(self) -> None:
        client = _build_client()
        async with client:
            resp = await client.get("/api/clearance/latest", headers=_AUTH)
            body = await resp.read()
            assert body == b""


# ---------------------------------------------------------------------------
# GET /api/clearance/latest — after valid POST
# ---------------------------------------------------------------------------


class TestGetClearanceLatestAfterValidPost:
    async def test_returns_200_after_valid_post(self) -> None:
        client = _build_client()
        async with client:
            post = await client.post(
                "/api/clearance", json=_valid_payload(), headers=_AUTH
            )
            assert post.status == 204
            resp = await client.get("/api/clearance/latest", headers=_AUTH)
            assert resp.status == 200

    async def test_response_contains_domain(self) -> None:
        client = _build_client()
        async with client:
            await client.post("/api/clearance", json=_valid_payload(), headers=_AUTH)
            resp = await client.get("/api/clearance/latest", headers=_AUTH)
            data = await resp.json()
            assert "domain" in data
            assert data["domain"] == ".fbref.com"

    async def test_response_contains_expires_at(self) -> None:
        client = _build_client()
        async with client:
            await client.post("/api/clearance", json=_valid_payload(), headers=_AUTH)
            resp = await client.get("/api/clearance/latest", headers=_AUTH)
            data = await resp.json()
            assert "expires_at" in data

    async def test_response_does_not_contain_raw_clearance(self) -> None:
        client = _build_client()
        async with client:
            await client.post("/api/clearance", json=_valid_payload(), headers=_AUTH)
            resp = await client.get("/api/clearance/latest", headers=_AUTH)
            data = await resp.json()
            assert "clearance" not in data

    async def test_response_does_not_contain_profile_id(self) -> None:
        client = _build_client()
        async with client:
            await client.post("/api/clearance", json=_valid_payload(), headers=_AUTH)
            resp = await client.get("/api/clearance/latest", headers=_AUTH)
            data = await resp.json()
            assert "profile_id" not in data

    async def test_response_does_not_contain_worker_id(self) -> None:
        client = _build_client()
        async with client:
            await client.post("/api/clearance", json=_valid_payload(), headers=_AUTH)
            resp = await client.get("/api/clearance/latest", headers=_AUTH)
            data = await resp.json()
            assert "worker_id" not in data


# ---------------------------------------------------------------------------
# Invalid POST does not update the store
# ---------------------------------------------------------------------------


class TestInvalidPostDoesNotUpdateStore:
    async def test_missing_field_post_leaves_store_empty(self) -> None:
        p = _valid_payload()
        bad_payload = {k: v for k, v in p.items() if k != "clearance"}
        client = _build_client()
        async with client:
            post = await client.post(
                "/api/clearance", json=bad_payload, headers=_AUTH
            )
            assert post.status == 422
            resp = await client.get("/api/clearance/latest", headers=_AUTH)
            assert resp.status == 204

    async def test_invalid_domain_post_leaves_store_empty(self) -> None:
        bad_payload = {**_valid_payload(), "domain": "evil.com"}

        client = _build_client()
        async with client:
            post = await client.post(
                "/api/clearance", json=bad_payload, headers=_AUTH
            )
            assert post.status == 422
            resp = await client.get("/api/clearance/latest", headers=_AUTH)
            assert resp.status == 204

    async def test_invalid_post_after_valid_does_not_overwrite(self) -> None:
        bad_payload = {**_valid_payload(), "domain": "evil.com"}

        client = _build_client()
        async with client:
            await client.post("/api/clearance", json=_valid_payload(), headers=_AUTH)
            await client.post("/api/clearance", json=bad_payload, headers=_AUTH)
            resp = await client.get("/api/clearance/latest", headers=_AUTH)
            assert resp.status == 200
            data = await resp.json()
            assert data["domain"] == ".fbref.com"


# ---------------------------------------------------------------------------
# Second valid POST overwrites the store
# ---------------------------------------------------------------------------


class TestSecondValidPostOverwrites:
    async def test_second_valid_post_updates_domain(self) -> None:
        second_payload = _valid_payload(domain="fbref.com")
        client = _build_client()
        async with client:
            await client.post("/api/clearance", json=_valid_payload(), headers=_AUTH)
            await client.post(
                "/api/clearance", json=second_payload, headers=_AUTH
            )
            resp = await client.get("/api/clearance/latest", headers=_AUTH)
            data = await resp.json()
            assert data["domain"] == "fbref.com"

    async def test_second_valid_post_updates_expires_at(self) -> None:
        first_payload = _valid_payload(expires_offset_s=3600)
        second_payload = _valid_payload(expires_offset_s=7200)
        client = _build_client()
        async with client:
            await client.post("/api/clearance", json=first_payload, headers=_AUTH)
            first_resp = await client.get("/api/clearance/latest", headers=_AUTH)
            first_data = await first_resp.json()
            await client.post("/api/clearance", json=second_payload, headers=_AUTH)
            resp = await client.get("/api/clearance/latest", headers=_AUTH)
            data = await resp.json()
            assert data["expires_at"] == second_payload["expires_at"]
            assert data["expires_at"] != first_data["expires_at"]
