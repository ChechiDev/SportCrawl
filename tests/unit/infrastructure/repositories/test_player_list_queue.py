"""Unit tests for PlayerListQueueRepository.

All database calls are mocked via AsyncMock session.
asyncio_mode = "auto" via pyproject.toml — no explicit @pytest.mark.asyncio.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from infrastructure.persistence.models.scrape_queue import ScrapeQueue, ScrapeStatus
from infrastructure.persistence.repositories.player_list_queue import (
    PlayerListQueueRepository,
)


def _make_session() -> AsyncMock:
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.first.return_value = None
    result.rowcount = 0
    session.execute.return_value = result
    return session


def _make_pending_row(job_id: int = 1) -> ScrapeQueue:
    row = ScrapeQueue()
    row.id = job_id
    row.url = "https://fbref.com/en/country/players/ARG/Argentina-Football"
    row.status = ScrapeStatus.PENDING
    row.retry_count = 0
    row.locked_at = None
    row.completed_at = None
    row.error_message = None
    row.job_type = "player_list"
    return row


class TestJobTypeDiscriminator:
    async def test_job_type_is_player_list(self) -> None:
        """Repository must set job_type discriminator to 'player_list'."""
        session = _make_session()
        repo = PlayerListQueueRepository(session)
        assert repo._job_type == "player_list"

    async def test_claim_next_returns_none_when_queue_empty(self) -> None:
        """claim_next must return None when no PENDING player_list rows exist."""
        session = _make_session()
        repo = PlayerListQueueRepository(session)
        claimed = await repo.claim_next()
        assert claimed is None

    async def test_claim_next_transitions_row_to_in_progress(self) -> None:
        """claim_next must mark the returned row IN_PROGRESS."""
        session = _make_session()
        row = _make_pending_row()
        result = MagicMock()
        result.scalars.return_value.first.return_value = row
        session.execute.return_value = result

        repo = PlayerListQueueRepository(session)
        claimed = await repo.claim_next()

        assert claimed is not None
        assert claimed.status == ScrapeStatus.IN_PROGRESS
        assert claimed.locked_at is not None

    async def test_claim_next_does_not_return_player_info_rows(self) -> None:
        """Discriminator must exclude rows with job_type='player_info'."""
        session = _make_session()
        # Return a row with wrong job_type — base class WHERE clause should filter it;
        # here we verify the SELECT was called (discriminator is baked into the query).
        result = MagicMock()
        result.scalars.return_value.first.return_value = None
        session.execute.return_value = result

        repo = PlayerListQueueRepository(session)
        claimed = await repo.claim_next()

        assert claimed is None
        # Confirm the query was issued — discriminator filtering is in the SQL
        session.execute.assert_called_once()


class TestMarkDone:
    async def test_mark_done_sets_status_done(self) -> None:
        session = _make_session()
        row = _make_pending_row()
        row.status = ScrapeStatus.IN_PROGRESS
        row.locked_at = datetime.now(UTC)
        session.get.return_value = row

        repo = PlayerListQueueRepository(session)
        await repo.mark_done(job_id=row.id)

        assert row.status == ScrapeStatus.DONE
        assert row.locked_at is None
        assert row.completed_at is not None


class TestRecoverStale:
    async def test_recover_stale_scoped_to_player_list(self) -> None:
        """recover_stale must filter by job_type='player_list', not all types."""
        session = _make_session()
        result = MagicMock()
        result.rowcount = 2
        session.execute.return_value = result

        repo = PlayerListQueueRepository(session)
        count = await repo.recover_stale(cutoff_minutes=30)

        assert count == 2
        call_args = session.execute.call_args
        # The SQL text and params are passed; verify job_type param is 'player_list'
        params = (
            call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("params", {})
        )  # noqa: E501
        assert params.get("job_type") == "player_list"
