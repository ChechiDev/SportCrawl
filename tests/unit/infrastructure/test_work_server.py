"""Unit tests for infrastructure.work_server.server (Phase 3 — tasks 3.1 + 3.2).

Tests use aiohttp TestClient and AsyncMock WorkQueuePort doubles.
No real DB or network required.

Covers (REQ-9.1, REQ-9.2, REQ-9.3, REQ-9.4):
- GET /health → 200 with no auth required
- Bearer auth middleware: missing/wrong/malformed header → 401
- Valid token → handler reached (not 401)
- POST /jobs valid batch → 201 + jobs[]/rejected[]
- POST /jobs missing urls field → 422
- POST /jobs non-JSON body → 400
- GET /jobs/{id} found → 200
- GET /jobs/{id} not found → 404
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from core.exceptions.repository import DuplicateError
from infrastructure.persistence.adapters.work_queue import JobRecord
from ports.work_queue import WorkQueuePort

# ---------------------------------------------------------------------------
# Token used in all tests
# ---------------------------------------------------------------------------

_TOKEN = "test-secret-token"


# ---------------------------------------------------------------------------
# Fake WorkQueuePort
# ---------------------------------------------------------------------------


class FakeWorkQueuePort:
    """In-memory fake that satisfies WorkQueuePort structurally."""

    def __init__(self) -> None:
        self.enqueue = AsyncMock()
        self.get_job = AsyncMock()


def _make_record(id: int = 1, url: str = "https://fbref.com/en/page", status: str = "PENDING") -> JobRecord:
    return JobRecord(id=id, url=url, status=status)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _build_client(port: FakeWorkQueuePort, token: str = _TOKEN) -> TestClient:
    """Build a TestClient wired to a create_app instance."""
    from infrastructure.work_server.server import create_app

    app = create_app(port, token)
    return TestClient(TestServer(app))


# ---------------------------------------------------------------------------
# Phase 3.1 — Auth middleware + /health
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    """GET /health must return 200 with no Authorization required (REQ-9.1)."""

    async def test_health_returns_200_no_auth(self) -> None:
        port = FakeWorkQueuePort()
        client = _build_client(port)
        async with client:
            resp = await client.get("/health")
            assert resp.status == 200

    async def test_health_returns_json_with_status_field(self) -> None:
        port = FakeWorkQueuePort()
        client = _build_client(port)
        async with client:
            resp = await client.get("/health")
            body = await resp.json()
            assert "status" in body

    async def test_health_skips_auth_middleware(self) -> None:
        """GET /health must not be blocked by auth even with no Authorization header."""
        port = FakeWorkQueuePort()
        client = _build_client(port)
        async with client:
            resp = await client.get("/health")
            assert resp.status != 401


class TestBearerAuthMiddleware:
    """REQ-9.2: all routes except /health require valid Bearer token."""

    async def test_missing_authorization_header_returns_401(self) -> None:
        port = FakeWorkQueuePort()
        client = _build_client(port)
        async with client:
            resp = await client.post("/jobs", json={"urls": ["https://fbref.com/en/x"]})
            assert resp.status == 401

    async def test_wrong_token_returns_401(self) -> None:
        port = FakeWorkQueuePort()
        client = _build_client(port)
        async with client:
            resp = await client.post(
                "/jobs",
                json={"urls": ["https://fbref.com/en/x"]},
                headers={"Authorization": "Bearer wrong-token"},
            )
            assert resp.status == 401

    async def test_malformed_header_not_bearer_returns_401(self) -> None:
        port = FakeWorkQueuePort()
        client = _build_client(port)
        async with client:
            resp = await client.post(
                "/jobs",
                json={"urls": ["https://fbref.com/en/x"]},
                headers={"Authorization": f"NotBearer {_TOKEN}"},
            )
            assert resp.status == 401

    async def test_valid_token_does_not_return_401(self) -> None:
        port = FakeWorkQueuePort()
        port.enqueue.return_value = _make_record()
        client = _build_client(port)
        async with client:
            resp = await client.post(
                "/jobs",
                json={"urls": ["https://fbref.com/en/x"]},
                headers={"Authorization": f"Bearer {_TOKEN}"},
            )
            assert resp.status != 401

    async def test_401_body_does_not_expose_token(self) -> None:
        """401 response body must not contain the expected token value."""
        port = FakeWorkQueuePort()
        client = _build_client(port)
        async with client:
            resp = await client.post(
                "/jobs",
                json={"urls": ["https://fbref.com/en/x"]},
                headers={"Authorization": "Bearer wrong-token"},
            )
            text = await resp.text()
            assert _TOKEN not in text


# ---------------------------------------------------------------------------
# Phase 3.2 — Handler tests
# ---------------------------------------------------------------------------


class TestPostJobsHandler:
    """POST /jobs handler (REQ-9.3)."""

    async def test_valid_batch_returns_201(self) -> None:
        port = FakeWorkQueuePort()
        port.enqueue.return_value = _make_record()
        client = _build_client(port)
        async with client:
            resp = await client.post(
                "/jobs",
                json={"urls": ["https://fbref.com/en/page"]},
                headers={"Authorization": f"Bearer {_TOKEN}"},
            )
            assert resp.status == 201

    async def test_valid_batch_returns_jobs_and_rejected(self) -> None:
        port = FakeWorkQueuePort()
        port.enqueue.return_value = _make_record()
        client = _build_client(port)
        async with client:
            resp = await client.post(
                "/jobs",
                json={"urls": ["https://fbref.com/en/page"]},
                headers={"Authorization": f"Bearer {_TOKEN}"},
            )
            body = await resp.json()
            assert "jobs" in body
            assert "rejected" in body

    async def test_valid_batch_returns_job_with_id_and_status(self) -> None:
        port = FakeWorkQueuePort()
        port.enqueue.return_value = _make_record(id=42)
        client = _build_client(port)
        async with client:
            resp = await client.post(
                "/jobs",
                json={"urls": ["https://fbref.com/en/page"]},
                headers={"Authorization": f"Bearer {_TOKEN}"},
            )
            body = await resp.json()
            assert len(body["jobs"]) == 1
            job = body["jobs"][0]
            assert job["id"] == 42
            assert job["status"] == "PENDING"

    async def test_duplicate_url_appears_in_rejected(self) -> None:
        port = FakeWorkQueuePort()
        port.enqueue.side_effect = DuplicateError("duplicate", cause=Exception("dup"))
        client = _build_client(port)
        async with client:
            resp = await client.post(
                "/jobs",
                json={"urls": ["https://fbref.com/en/dup"]},
                headers={"Authorization": f"Bearer {_TOKEN}"},
            )
            body = await resp.json()
            assert resp.status == 201
            assert len(body["rejected"]) == 1
            assert body["rejected"][0]["url"] == "https://fbref.com/en/dup"
            assert body["rejected"][0]["reason"] == "duplicate"

    async def test_missing_urls_field_returns_422(self) -> None:
        port = FakeWorkQueuePort()
        client = _build_client(port)
        async with client:
            resp = await client.post(
                "/jobs",
                json={"wrong_field": "value"},
                headers={"Authorization": f"Bearer {_TOKEN}"},
            )
            assert resp.status == 422

    async def test_non_json_body_returns_400(self) -> None:
        port = FakeWorkQueuePort()
        client = _build_client(port)
        async with client:
            resp = await client.post(
                "/jobs",
                data="not-json",
                headers={
                    "Authorization": f"Bearer {_TOKEN}",
                    "Content-Type": "text/plain",
                },
            )
            assert resp.status == 400

    async def test_batch_with_multiple_urls_returns_all(self) -> None:
        port = FakeWorkQueuePort()
        port.enqueue.side_effect = [
            _make_record(id=1, url="https://fbref.com/en/a"),
            _make_record(id=2, url="https://fbref.com/en/b"),
        ]
        client = _build_client(port)
        async with client:
            resp = await client.post(
                "/jobs",
                json={"urls": ["https://fbref.com/en/a", "https://fbref.com/en/b"]},
                headers={"Authorization": f"Bearer {_TOKEN}"},
            )
            body = await resp.json()
            assert len(body["jobs"]) == 2
            assert body["rejected"] == []


class TestGetJobHandler:
    """GET /jobs/{id} handler (REQ-9.4)."""

    async def test_found_job_returns_200(self) -> None:
        port = FakeWorkQueuePort()
        port.get_job.return_value = _make_record(id=5, status="PENDING")
        client = _build_client(port)
        async with client:
            resp = await client.get(
                "/jobs/5",
                headers={"Authorization": f"Bearer {_TOKEN}"},
            )
            assert resp.status == 200

    async def test_found_job_body_contains_id_and_status(self) -> None:
        port = FakeWorkQueuePort()
        port.get_job.return_value = _make_record(id=5, status="DONE")
        client = _build_client(port)
        async with client:
            resp = await client.get(
                "/jobs/5",
                headers={"Authorization": f"Bearer {_TOKEN}"},
            )
            body = await resp.json()
            assert body["id"] == 5
            assert body["status"] == "DONE"

    async def test_not_found_returns_404(self) -> None:
        port = FakeWorkQueuePort()
        port.get_job.return_value = None
        client = _build_client(port)
        async with client:
            resp = await client.get(
                "/jobs/9999",
                headers={"Authorization": f"Bearer {_TOKEN}"},
            )
            assert resp.status == 404
