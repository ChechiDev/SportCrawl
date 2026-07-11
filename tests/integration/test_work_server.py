"""Integration tests for the aiohttp work server (Phase 5 — tasks 5.1 + 5.2).

Uses aiohttp TestServer + real ScrapeQueueWorkAdapter on a testcontainers
Postgres database.

Covers (REQ-9.3, REQ-9.4, REQ-9.6):
- POST /jobs → PENDING row in DB (task 5.1)
- GET /jobs/{id} → 200 with correct status (task 5.1)
- Duplicate URL → appears in rejected[] (task 5.1)
- End-to-end: POST /jobs → JobLoop.run() → GET /jobs/{id} returns DONE (task 5.2)

Isolation: each test uses a unique URL suffix (UUID4) and the adapter_engine
fixture truncates sch_infra.scrape_queue rows after each test.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer
from sqlalchemy import text
from sqlalchemy.engine.url import URL
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from infrastructure.persistence.adapters.work_queue import ScrapeQueueWorkAdapter
from infrastructure.work_server.server import create_app

# ---------------------------------------------------------------------------
# Test constants
# ---------------------------------------------------------------------------

_TOKEN = "integration-test-token"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(loop_scope="function")
async def _ws_engine(_integration_db_url: URL):
    """Fresh async engine per test, disposed after."""
    engine = create_async_engine(_integration_db_url, echo=False)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(loop_scope="function")
async def adapter(_ws_engine) -> ScrapeQueueWorkAdapter:
    """Real ScrapeQueueWorkAdapter backed by the testcontainer Postgres.

    Cleans up all scrape_queue rows after each test to avoid cross-test
    contamination of count-based assertions in other modules.
    """
    factory = async_sessionmaker(_ws_engine, expire_on_commit=False)
    yield ScrapeQueueWorkAdapter(factory)

    async with _ws_engine.connect() as conn:
        await conn.execute(text("DELETE FROM sch_infra.scrape_queue"))
        await conn.commit()


@pytest_asyncio.fixture(loop_scope="function")
async def client(adapter: ScrapeQueueWorkAdapter) -> TestClient:
    """Wired TestClient using the real adapter."""
    app = create_app(adapter, _TOKEN)
    test_client = TestClient(TestServer(app))
    async with test_client:
        yield test_client


def _unique_url(label: str = "") -> str:
    """Generate a unique fbref.com URL for test isolation."""
    return f"https://fbref.com/integration-ws/{uuid.uuid4().hex}/{label}"


# ---------------------------------------------------------------------------
# Task 5.1 — Server + real DB
# ---------------------------------------------------------------------------


class TestWorkServerIntegration:
    """Integration tests: server + real DB adapter, no mocks."""

    async def test_post_jobs_creates_pending_row(self, client: TestClient) -> None:
        """POST /jobs → PENDING row in the DB (REQ-9.3)."""
        url = _unique_url("post-creates-pending")
        resp = await client.post(
            "/jobs",
            json={"urls": [url]},
            headers={"Authorization": f"Bearer {_TOKEN}"},
        )
        assert resp.status == 201
        body = await resp.json()
        assert len(body["jobs"]) == 1
        assert body["jobs"][0]["status"] == "PENDING"
        assert body["rejected"] == []

    async def test_get_job_returns_pending_status(self, client: TestClient) -> None:
        """GET /jobs/{id} returns the PENDING record after POST /jobs."""
        url = _unique_url("get-job-pending")
        post_resp = await client.post(
            "/jobs",
            json={"urls": [url]},
            headers={"Authorization": f"Bearer {_TOKEN}"},
        )
        job_id = (await post_resp.json())["jobs"][0]["id"]

        get_resp = await client.get(
            f"/jobs/{job_id}",
            headers={"Authorization": f"Bearer {_TOKEN}"},
        )
        assert get_resp.status == 200
        body = await get_resp.json()
        assert body["id"] == job_id
        assert body["status"] == "PENDING"

    async def test_duplicate_url_appears_in_rejected(self, client: TestClient) -> None:
        """Duplicate URL → rejected[] with reason=duplicate (REQ-9.3)."""
        url = _unique_url("duplicate")
        # First submission — should succeed
        await client.post(
            "/jobs",
            json={"urls": [url]},
            headers={"Authorization": f"Bearer {_TOKEN}"},
        )
        # Second submission — same URL → rejected
        resp = await client.post(
            "/jobs",
            json={"urls": [url]},
            headers={"Authorization": f"Bearer {_TOKEN}"},
        )
        body = await resp.json()
        assert resp.status == 201
        assert body["jobs"] == []
        assert len(body["rejected"]) == 1
        assert body["rejected"][0]["reason"] == "duplicate"

    async def test_get_job_not_found_returns_404(self, client: TestClient) -> None:
        """GET /jobs/{id} → 404 when job does not exist (REQ-9.4)."""
        resp = await client.get(
            "/jobs/999999999",
            headers={"Authorization": f"Bearer {_TOKEN}"},
        )
        assert resp.status == 404

    async def test_health_returns_200_without_auth(self, client: TestClient) -> None:
        """GET /health → 200 with no Authorization header (REQ-9.1)."""
        resp = await client.get("/health")
        assert resp.status == 200
        body = await resp.json()
        assert body["status"] == "ok"


# ---------------------------------------------------------------------------
# Task 5.2 — End-to-end: POST /jobs → JobLoop.run() → GET /jobs/{id} = DONE
# ---------------------------------------------------------------------------


class TestWorkServerEndToEnd:
    """End-to-end: submit job → drain via JobLoop → verify DONE status."""

    async def test_jobloop_drains_pending_to_done(
        self,
        _ws_engine,
        adapter: ScrapeQueueWorkAdapter,
        client: TestClient,
    ) -> None:
        """POST /jobs → JobLoop.run() → GET /jobs/{id} returns DONE.

        Uses a real JobLoop wired against the same DB but with a fake scraper
        that immediately succeeds, so the job transitions PENDING → DONE
        without needing a real browser/network.
        """
        import uuid as uuid_module
        from unittest.mock import AsyncMock, MagicMock
        from sqlalchemy.ext.asyncio import AsyncSession
        from infrastructure.persistence.models.provenance import Provenance, ProvenanceOutcome
        from infrastructure.persistence.repositories.provenance import ProvenanceRepository
        from infrastructure.persistence.repositories.scrape_queue import ScrapeQueueRepository
        from infrastructure.persistence.session import get_session
        from infrastructure.jobs.job_loop import JobLoop
        from config.settings import ScrapingSettings

        url = _unique_url("e2e-done")

        # Submit the job
        post_resp = await client.post(
            "/jobs",
            json={"urls": [url]},
            headers={"Authorization": f"Bearer {_TOKEN}"},
        )
        assert post_resp.status == 201
        job_id = (await post_resp.json())["jobs"][0]["id"]

        # Build a fake scraper that "succeeds" without real network
        def _fake_scraper_factory(scrape_url: str):
            scraper = MagicMock()
            scraper.fetch_and_parse = AsyncMock(return_value=None)
            scraper.last_html = "<html>fake</html>"
            return scraper

        # ProvenanceFactory signature: (url: str, outcome_str: str, content_hash: str, run_id: UUID)
        # Provenance ORM model uses keyword arguments with outcome as ProvenanceOutcome enum.
        def _provenance_factory(
            prov_url: str,
            outcome_str: str,
            content_hash: str,
            run_id: uuid_module.UUID,
        ) -> Provenance:
            outcome = ProvenanceOutcome[outcome_str]  # "SUCCESS" → ProvenanceOutcome.SUCCESS
            return Provenance(
                url=prov_url,
                outcome=outcome,
                content_hash=content_hash,
                run_id=run_id,
            )

        factory = async_sessionmaker(_ws_engine, expire_on_commit=False)
        scraping_settings = ScrapingSettings(work_server_token="test-token")

        job_loop = JobLoop(
            session_factory=lambda: get_session(factory),
            scraper_factory=_fake_scraper_factory,
            queue_repo_factory=lambda session: ScrapeQueueRepository(session),
            provenance_repo_factory=lambda session: ProvenanceRepository(session),
            provenance_factory=_provenance_factory,
            settings=scraping_settings,
        )

        # Drain the queue
        await job_loop.run()

        # Verify the job reached DONE status
        get_resp = await client.get(
            f"/jobs/{job_id}",
            headers={"Authorization": f"Bearer {_TOKEN}"},
        )
        assert get_resp.status == 200
        body = await get_resp.json()
        assert body["status"] == "DONE", (
            f"Expected DONE, got {body['status']!r}. "
            "JobLoop may not have processed the job."
        )
