"""Integration tests for PlayerInfoQueueRepository.release_to_pending().

Uses a real PostgreSQL database via testcontainers. These tests verify
that release_to_pending() transitions IN_PROGRESS → PENDING without
incrementing retry counters or advancing failure state.

All tests use async_session from integration/conftest.py (rolled back after each test).
"""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.persistence.models.scrape_queue import ScrapeQueue, ScrapeStatus
from infrastructure.persistence.repositories.player_info_queue import (
    PlayerInfoQueueRepository,
)

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _insert_pending(
    session: AsyncSession,
    url: str = "https://fbref.com/en/players/abc123/test-player",
) -> ScrapeQueue:
    """Insert one PENDING player_info job; flushes but does not commit."""
    row = ScrapeQueue(
        url=url,
        domain="fbref.com",
        job_type="player_info",
        status=ScrapeStatus.PENDING,
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return row


async def _claim(session: AsyncSession, job_id: int) -> None:
    repo = PlayerInfoQueueRepository(session)
    row = await repo.claim_by_id(job_id)
    assert row is not None
    await session.flush()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_release_to_pending_transitions_in_progress(
    async_session: AsyncSession,
) -> None:
    row = await _insert_pending(async_session)
    await _claim(async_session, row.id)

    # Refresh to confirm IN_PROGRESS
    await async_session.refresh(row)
    assert row.status == ScrapeStatus.IN_PROGRESS

    repo = PlayerInfoQueueRepository(async_session)
    released = await repo.release_to_pending(row.id)
    await async_session.flush()

    assert released is True
    await async_session.refresh(row)
    assert row.status == ScrapeStatus.PENDING
    assert row.locked_at is None


async def test_release_to_pending_does_not_increment_retry_count(
    async_session: AsyncSession,
) -> None:
    row = await _insert_pending(
        async_session,
        url="https://fbref.com/en/players/def456/retry-player",
    )
    original_retry = row.retry_count
    await _claim(async_session, row.id)

    repo = PlayerInfoQueueRepository(async_session)
    await repo.release_to_pending(row.id)
    await async_session.flush()

    await async_session.refresh(row)
    assert row.retry_count == original_retry


async def test_release_to_pending_noop_for_pending_job(
    async_session: AsyncSession,
) -> None:
    """Releasing a PENDING job (not IN_PROGRESS) returns False."""
    row = await _insert_pending(
        async_session,
        url="https://fbref.com/en/players/ghi789/pending-player",
    )

    repo = PlayerInfoQueueRepository(async_session)
    released = await repo.release_to_pending(row.id)
    await async_session.flush()

    assert released is False
    await async_session.refresh(row)
    assert row.status == ScrapeStatus.PENDING


async def test_release_to_pending_noop_for_nonexistent_job(
    async_session: AsyncSession,
) -> None:
    repo = PlayerInfoQueueRepository(async_session)
    released = await repo.release_to_pending(99999999)
    await async_session.flush()

    assert released is False
