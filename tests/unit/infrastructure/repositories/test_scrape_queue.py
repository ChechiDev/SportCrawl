"""Unit tests for ScrapeQueueRepository base class.

Verifies that the base class is generic (parameterized by job_type) and that
PlayerInfoQueueRepository wires the correct job_type.
asyncio_mode = "auto" via pyproject.toml — no explicit @pytest.mark.asyncio.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from infrastructure.persistence.models.scrape_queue import ScrapeQueue, ScrapeStatus
from infrastructure.persistence.repositories.player_info_queue import (
    PlayerInfoQueueRepository,
)
from infrastructure.persistence.repositories.scrape_queue import ScrapeQueueRepository

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session() -> AsyncMock:
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.first.return_value = None
    result.rowcount = 0
    session.execute.return_value = result
    return session


def _make_pending_row(job_id: int = 1, job_type: str = "player_info") -> ScrapeQueue:
    row = ScrapeQueue()
    row.id = job_id
    row.url = f"https://fbref.com/en/players/abc{job_id:05d}/Player"
    row.status = ScrapeStatus.PENDING
    row.retry_count = 0
    row.locked_at = None
    row.completed_at = None
    row.error_message = None
    row.job_type = job_type
    return row


# ---------------------------------------------------------------------------
# ScrapeQueueRepository base — generic job_type
# ---------------------------------------------------------------------------


class TestScrapeQueueRepositoryBase:
    async def test_claim_next_uses_configured_job_type(self) -> None:
        """claim_next must filter by the job_type passed to __init__."""
        session = _make_session()
        row = _make_pending_row(job_type="test_job")
        result = MagicMock()
        result.scalars.return_value.first.return_value = row
        session.execute.return_value = result

        repo = ScrapeQueueRepository(session, job_type="test_job")
        claimed = await repo.claim_next()

        assert claimed is not None
        # The WHERE clause embedded job_type — verify it by inspecting what was
        # passed to session.execute (the SQLAlchemy stmt will have the filter).
        session.execute.assert_called_once()
        stmt_arg = session.execute.call_args[0][0]
        # Confirm that the compiled WHERE clause references our job_type value
        compiled = str(stmt_arg.compile(compile_kwargs={"literal_binds": True}))
        assert "test_job" in compiled

    async def test_claim_next_player_info_job_type(self) -> None:
        """PlayerInfoQueueRepository must default to job_type='player_info'."""
        session = _make_session()
        row = _make_pending_row(job_type="player_info")
        result = MagicMock()
        result.scalars.return_value.first.return_value = row
        session.execute.return_value = result

        repo = PlayerInfoQueueRepository(session)
        claimed = await repo.claim_next()

        assert claimed is not None
        stmt_arg = session.execute.call_args[0][0]
        compiled = str(stmt_arg.compile(compile_kwargs={"literal_binds": True}))
        assert "player_info" in compiled

    async def test_base_class_with_arbitrary_job_type(self) -> None:
        """Base class must work for any job_type, not just 'player_info'."""
        session = _make_session()
        result = MagicMock()
        result.scalars.return_value.first.return_value = None
        session.execute.return_value = result

        repo = ScrapeQueueRepository(session, job_type="national_team")
        claimed = await repo.claim_next()

        assert claimed is None
        stmt_arg = session.execute.call_args[0][0]
        compiled = str(stmt_arg.compile(compile_kwargs={"literal_binds": True}))
        assert "national_team" in compiled
