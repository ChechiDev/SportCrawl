"""Unit tests for TeamListQueueRepository.

All database calls are mocked via AsyncMock session.
asyncio_mode = "auto" via pyproject.toml — no explicit @pytest.mark.asyncio.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from infrastructure.persistence.models.scrape_queue import ScrapeQueue, ScrapeStatus
from infrastructure.persistence.repositories.team_list_queue import (
    TeamListQueueRepository,
)


def _make_session() -> AsyncMock:
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.first.return_value = None
    result.rowcount = 0
    session.execute.return_value = result
    return session


def _make_pending_row(
    job_id: int = 1,
    url: str = "https://fbref.com/en/country/clubs/ARG/Argentina-Football",
) -> ScrapeQueue:
    row = ScrapeQueue()
    row.id = job_id
    row.url = url
    row.status = ScrapeStatus.PENDING
    row.retry_count = 0
    row.locked_at = None
    row.completed_at = None
    row.error_message = None
    row.job_type = "team_list"
    return row


class TestJobTypeDiscriminator:
    async def test_job_type_is_team_list(self) -> None:
        """Repository must set job_type discriminator to 'team_list'."""
        session = _make_session()
        repo = TeamListQueueRepository(session)
        assert repo._job_type == "team_list"

    async def test_claim_next_returns_none_when_queue_empty(self) -> None:
        """claim_next must return None when no PENDING team_list rows exist."""
        session = _make_session()
        repo = TeamListQueueRepository(session)
        claimed = await repo.claim_next()
        assert claimed is None

    async def test_claim_next_transitions_row_to_in_progress(self) -> None:
        """claim_next must mark the returned row IN_PROGRESS."""
        session = _make_session()
        row = _make_pending_row()
        result = MagicMock()
        result.scalars.return_value.first.return_value = row
        session.execute.return_value = result

        repo = TeamListQueueRepository(session)
        claimed = await repo.claim_next()

        assert claimed is not None
        assert claimed.status == ScrapeStatus.IN_PROGRESS
        assert claimed.locked_at is not None

    async def test_claim_next_does_not_return_player_list_rows(self) -> None:
        """Discriminator must exclude rows with job_type='player_list'."""
        session = _make_session()
        result = MagicMock()
        result.scalars.return_value.first.return_value = None
        session.execute.return_value = result

        repo = TeamListQueueRepository(session)
        claimed = await repo.claim_next()

        assert claimed is None
        session.execute.assert_called_once()


class TestClaimNextCountryFilter:
    async def test_claim_next_no_filter_returns_any_pending(self) -> None:
        """claim_next(country_filter=None) claims any PENDING team_list row."""
        session = _make_session()
        row = _make_pending_row()
        result = MagicMock()
        result.scalars.return_value.first.return_value = row
        session.execute.return_value = result

        repo = TeamListQueueRepository(session)
        claimed = await repo.claim_next_filtered(country_filter=None)

        assert claimed is not None
        assert claimed.status == ScrapeStatus.IN_PROGRESS
        # Only one query issued (no extra subquery call)
        assert session.execute.call_count == 1

    async def test_claim_next_with_filter_issues_query(self) -> None:
        """claim_next_filtered(country_filter={'ARG'}) must issue a query to the DB."""
        session = _make_session()
        row = _make_pending_row()
        result = MagicMock()
        result.scalars.return_value.first.return_value = row
        session.execute.return_value = result

        repo = TeamListQueueRepository(session)
        claimed = await repo.claim_next_filtered(country_filter={"ARG"})

        assert claimed is not None
        assert claimed.status == ScrapeStatus.IN_PROGRESS
        session.execute.assert_called_once()

    async def test_claim_next_with_filter_returns_none_when_no_match(self) -> None:
        """claim_next_filtered with filter returns None when no matching PENDING row."""
        session = _make_session()
        # Session returns empty result (no rows for filtered country)
        result = MagicMock()
        result.scalars.return_value.first.return_value = None
        session.execute.return_value = result

        repo = TeamListQueueRepository(session)
        claimed = await repo.claim_next_filtered(country_filter={"BRA"})

        assert claimed is None


class TestMarkDone:
    async def test_mark_done_sets_status_done(self) -> None:
        session = _make_session()
        row = _make_pending_row()
        row.status = ScrapeStatus.IN_PROGRESS
        row.locked_at = datetime.now(UTC)
        session.get.return_value = row

        repo = TeamListQueueRepository(session)
        await repo.mark_done(job_id=row.id)

        assert row.status == ScrapeStatus.DONE
        assert row.locked_at is None
        assert row.completed_at is not None


class TestMarkFailed:
    async def test_mark_failed_below_ceiling_returns_to_pending(self) -> None:
        """mark_failed below retry ceiling must re-queue as PENDING."""
        session = _make_session()
        row = _make_pending_row()
        row.status = ScrapeStatus.IN_PROGRESS
        row.retry_count = 0
        session.get.return_value = row

        repo = TeamListQueueRepository(session)
        await repo.mark_failed(job_id=row.id, error="timeout")

        assert row.status == ScrapeStatus.PENDING
        assert row.retry_count == 1
        assert row.error_message == "timeout"

    async def test_mark_failed_at_ceiling_sets_failed(self) -> None:
        """mark_failed at retry ceiling (3) must set status to FAILED."""
        session = _make_session()
        row = _make_pending_row()
        row.status = ScrapeStatus.IN_PROGRESS
        row.retry_count = 2  # one more → ceiling
        session.get.return_value = row

        repo = TeamListQueueRepository(session)
        await repo.mark_failed(job_id=row.id, error="browser crash")

        assert row.status == ScrapeStatus.FAILED
        assert row.retry_count == 3
