"""Integration tests for ScrapeQueueRepository.peek_pending_ids and claim_by_id.

Covers:
- peek_pending_ids: returns PENDING job IDs without claiming them
- peek_pending_ids: respects job_type filter
- peek_pending_ids: returns empty list when no PENDING jobs
- peek_pending_ids: respects limit parameter
- After peek, jobs are still PENDING (not claimed)
- claim_by_id: claims a PENDING job and returns the ScrapeQueue row
- claim_by_id: returns None for an already IN_PROGRESS job
- claim_by_id: returns None for a DONE job
- claim_by_id: returns None for a non-existent job ID
- claim_by_id: sets status=IN_PROGRESS and locked_at is not None
- Two concurrent claim_by_id calls on the same job: exactly one succeeds

All tests use async_session from integration/conftest.py (rolled back after each test).
"""

from __future__ import annotations

import asyncio
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from infrastructure.persistence.models.scrape_queue import ScrapeQueue, ScrapeStatus
from infrastructure.persistence.repositories.scrape_queue import ScrapeQueueRepository

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_JOB_TYPE = "player_info"
_OTHER_JOB_TYPE = "player_discovery"


async def _insert_job(
    session: AsyncSession,
    url: str,
    *,
    job_type: str = _JOB_TYPE,
    status: ScrapeStatus = ScrapeStatus.PENDING,
) -> ScrapeQueue:
    """Insert a scrape_queue row directly and flush (no commit)."""
    row = ScrapeQueue(
        url=url,
        domain="fbref.com",
        status=status,
        job_type=job_type,
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return row


def _make_repo(session: AsyncSession) -> ScrapeQueueRepository:
    return ScrapeQueueRepository(session, job_type=_JOB_TYPE)


# ---------------------------------------------------------------------------
# peek_pending_ids
# ---------------------------------------------------------------------------


class TestPeekPendingIds:
    async def test_returns_pending_job_ids(self, async_session: AsyncSession) -> None:
        """peek_pending_ids returns the IDs of PENDING rows for the right job_type."""
        repo = _make_repo(async_session)
        row1 = await _insert_job(async_session, "https://fbref.com/p1")
        row2 = await _insert_job(async_session, "https://fbref.com/p2")

        ids = await repo.peek_pending_ids(limit=10)

        assert row1.id in ids
        assert row2.id in ids

    async def test_respects_job_type_filter(self, async_session: AsyncSession) -> None:
        """peek_pending_ids only returns IDs for the repository's job_type."""
        repo = _make_repo(async_session)
        own_row = await _insert_job(
            async_session, "https://fbref.com/own", job_type=_JOB_TYPE
        )
        other_row = await _insert_job(
            async_session, "https://fbref.com/other", job_type=_OTHER_JOB_TYPE
        )

        ids = await repo.peek_pending_ids(limit=10)

        assert own_row.id in ids
        assert other_row.id not in ids

    async def test_returns_empty_when_no_pending(
        self, async_session: AsyncSession
    ) -> None:
        """peek_pending_ids returns an empty list when no PENDING rows exist."""
        repo = _make_repo(async_session)
        # Insert a DONE row — should not appear
        row = await _insert_job(async_session, "https://fbref.com/done-row")
        row.status = ScrapeStatus.DONE
        await async_session.flush()

        ids = await repo.peek_pending_ids(limit=10)

        assert row.id not in ids

    async def test_respects_limit(self, async_session: AsyncSession) -> None:
        """peek_pending_ids(limit=2) returns at most 2 IDs."""
        repo = _make_repo(async_session)
        for i in range(5):
            await _insert_job(async_session, f"https://fbref.com/lim{i}")

        ids = await repo.peek_pending_ids(limit=2)

        assert len(ids) <= 2

    async def test_jobs_remain_pending_after_peek(
        self, async_session: AsyncSession
    ) -> None:
        """After peek_pending_ids, the rows are still PENDING — not claimed."""
        repo = _make_repo(async_session)
        row = await _insert_job(async_session, "https://fbref.com/still-pending")

        ids = await repo.peek_pending_ids(limit=10)

        assert row.id in ids
        await async_session.refresh(row)
        assert row.status == ScrapeStatus.PENDING
        assert row.locked_at is None


# ---------------------------------------------------------------------------
# claim_by_id
# ---------------------------------------------------------------------------


class TestClaimById:
    async def test_claims_pending_job_and_returns_row(
        self, async_session: AsyncSession
    ) -> None:
        """claim_by_id returns the ScrapeQueue row and transitions it to IN_PROGRESS."""
        repo = _make_repo(async_session)
        row = await _insert_job(async_session, "https://fbref.com/claim1")

        claimed = await repo.claim_by_id(row.id)

        assert claimed is not None
        assert claimed.id == row.id
        assert claimed.status == ScrapeStatus.IN_PROGRESS

    async def test_sets_locked_at(self, async_session: AsyncSession) -> None:
        """claim_by_id sets locked_at to a non-None datetime."""
        repo = _make_repo(async_session)
        row = await _insert_job(async_session, "https://fbref.com/lockat")

        claimed = await repo.claim_by_id(row.id)

        assert claimed is not None
        assert claimed.locked_at is not None
        assert isinstance(claimed.locked_at, datetime)

    async def test_returns_none_for_in_progress_job(
        self, async_session: AsyncSession
    ) -> None:
        """claim_by_id returns None if the job is already IN_PROGRESS."""
        repo = _make_repo(async_session)
        row = await _insert_job(
            async_session,
            "https://fbref.com/inprog",
            status=ScrapeStatus.IN_PROGRESS,
        )

        claimed = await repo.claim_by_id(row.id)

        assert claimed is None

    async def test_returns_none_for_done_job(self, async_session: AsyncSession) -> None:
        """claim_by_id returns None if the job is already DONE."""
        repo = _make_repo(async_session)
        row = await _insert_job(
            async_session,
            "https://fbref.com/donejo",
            status=ScrapeStatus.DONE,
        )

        claimed = await repo.claim_by_id(row.id)

        assert claimed is None

    async def test_returns_none_for_nonexistent_id(
        self, async_session: AsyncSession
    ) -> None:
        """claim_by_id returns None when the job ID does not exist."""
        repo = _make_repo(async_session)

        claimed = await repo.claim_by_id(999_999_999)

        assert claimed is None

    async def test_status_is_in_progress_after_claim(
        self, async_session: AsyncSession
    ) -> None:
        """After claim_by_id, refreshing the row shows IN_PROGRESS and locked_at set."""
        repo = _make_repo(async_session)
        row = await _insert_job(async_session, "https://fbref.com/statuscheck")

        await repo.claim_by_id(row.id)
        await async_session.refresh(row)

        assert row.status == ScrapeStatus.IN_PROGRESS
        assert row.locked_at is not None

    async def test_concurrent_claim_exactly_one_succeeds(
        self, _integration_db_url: object
    ) -> None:
        """Two concurrent claim_by_id calls on the same job: exactly one succeeds.

        Uses two independent sessions so FOR UPDATE SKIP LOCKED contention
        works correctly — a single shared session would not produce real locking.
        """
        from sqlalchemy.engine.url import URL

        db_url: URL = _integration_db_url  # type: ignore[assignment]  # fixture is URL
        engine_a = create_async_engine(db_url, echo=False)
        engine_b = create_async_engine(db_url, echo=False)

        # Insert the job with a fresh engine (to ensure it's committed)
        engine_setup = create_async_engine(db_url, echo=False)
        async with engine_setup.connect() as conn:
            await conn.begin()
            async with AsyncSession(bind=conn, expire_on_commit=False) as setup_session:
                row = ScrapeQueue(
                    url="https://fbref.com/concurrent-claim-test",
                    domain="fbref.com",
                    status=ScrapeStatus.PENDING,
                    job_type=_JOB_TYPE,
                )
                setup_session.add(row)
                await setup_session.flush()
                await setup_session.refresh(row)
                job_id = row.id
            await conn.commit()
        await engine_setup.dispose()

        results: list[ScrapeQueue | None] = []

        async def _claim_with_engine(engine: AsyncEngine) -> ScrapeQueue | None:

            async with engine.connect() as conn:
                async with conn.begin():
                    async with AsyncSession(
                        bind=conn, expire_on_commit=False
                    ) as session:
                        repo = ScrapeQueueRepository(session, job_type=_JOB_TYPE)
                        claimed = await repo.claim_by_id(job_id)
                        await session.flush()
                    # commit happens here when conn.begin() context exits
                return claimed

        try:
            claimed_a, claimed_b = await asyncio.gather(
                _claim_with_engine(engine_a),
                _claim_with_engine(engine_b),
            )
        finally:
            await engine_a.dispose()
            await engine_b.dispose()

        results = [claimed_a, claimed_b]
        successes = [r for r in results if r is not None]
        failures = [r for r in results if r is None]

        assert len(successes) == 1, (
            f"Expected exactly 1 successful claim, got {len(successes)}: {results}"
        )
        assert len(failures) == 1
