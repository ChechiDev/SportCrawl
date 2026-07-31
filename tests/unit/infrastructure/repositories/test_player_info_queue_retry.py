"""Unit tests for PlayerInfoQueueRepository retry ceiling and recover_failed_job.

asyncio_mode = "auto" via pyproject.toml — no explicit @pytest.mark.asyncio.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest  # noqa: F401 — used as pytest.raises

from infrastructure.persistence.models.scrape_queue import ScrapeQueue, ScrapeStatus
from infrastructure.persistence.repositories.player_info_queue import (
    PlayerInfoQueueRepository,
    recover_failed_job,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_session() -> AsyncMock:
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.first.return_value = None
    result.rowcount = 0
    session.execute.return_value = result
    return session


def _make_job(
    job_id: int = 1,
    retry_count: int = 0,
    status: ScrapeStatus = ScrapeStatus.IN_PROGRESS,
    fk_url_registry_id: int | None = None,
) -> ScrapeQueue:
    row = ScrapeQueue()
    row.id = job_id
    row.url = f"https://fbref.com/en/players/abc{job_id:05d}/Player"
    row.status = status
    row.retry_count = retry_count
    row.locked_at = datetime.now(UTC) if status == ScrapeStatus.IN_PROGRESS else None
    row.completed_at = None
    row.error_message = None
    row.job_type = "player_info"
    row.fk_url_registry_id = fk_url_registry_id
    return row


# ---------------------------------------------------------------------------
# mark_failed retry ceiling tests
# ---------------------------------------------------------------------------


class TestMarkFailedRetryCeiling:
    async def test_below_ceiling_sets_pending(self) -> None:
        """mark_failed below the ceiling must transition to PENDING."""
        session = _make_session()
        row = _make_job(retry_count=0)
        session.get.return_value = row

        repo = PlayerInfoQueueRepository(session, max_queue_retries=5)
        await repo.mark_failed(row.id, "network error")

        assert row.status == ScrapeStatus.PENDING
        assert row.retry_count == 1
        assert row.error_message == "network error"
        assert row.locked_at is None

    async def test_at_ceiling_sets_failed(self) -> None:
        """mark_failed at the ceiling must transition to FAILED."""
        session = _make_session()
        row = _make_job(retry_count=4)  # will become 5 → FAILED
        session.get.return_value = row

        repo = PlayerInfoQueueRepository(session, max_queue_retries=5)
        await repo.mark_failed(row.id, "persistent error")

        assert row.status == ScrapeStatus.FAILED
        assert row.retry_count == 5
        assert row.completed_at is not None

    async def test_above_ceiling_sets_failed(self) -> None:
        """mark_failed above the ceiling must still transition to FAILED."""
        session = _make_session()
        row = _make_job(retry_count=6)
        session.get.return_value = row

        repo = PlayerInfoQueueRepository(session, max_queue_retries=5)
        await repo.mark_failed(row.id, "error")

        assert row.status == ScrapeStatus.FAILED

    async def test_retry_count_incremented_at_failure(self) -> None:
        """mark_failed must increment retry_count exactly once per call."""
        session = _make_session()
        row = _make_job(retry_count=2)
        session.get.return_value = row

        repo = PlayerInfoQueueRepository(session, max_queue_retries=5)
        await repo.mark_failed(row.id, "error")

        assert row.retry_count == 3

    async def test_default_max_queue_retries_is_five(self) -> None:
        """Default max_queue_retries must be 5 (ceiling at retry_count=4→5)."""
        session = _make_session()
        row = _make_job(retry_count=4)
        session.get.return_value = row

        repo = PlayerInfoQueueRepository(session)  # no explicit max_queue_retries
        await repo.mark_failed(row.id, "error")

        assert row.status == ScrapeStatus.FAILED


_GET_SESSION = (
    "infrastructure.persistence.repositories.player_info_queue.get_session"
)

# ---------------------------------------------------------------------------
# recover_failed_job validation tests
# ---------------------------------------------------------------------------


class TestRecoverFailedJob:
    def _make_session_factory(self, session: AsyncMock) -> MagicMock:
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)
        factory = MagicMock()
        factory.return_value = cm
        return factory

    async def test_raises_when_job_not_found(self) -> None:
        """recover_failed_job must raise ValueError when job_id does not exist."""
        session = _make_session()
        session.get.return_value = None
        factory = self._make_session_factory(session)

        with patch(_GET_SESSION) as mock_gs:
            mock_gs.return_value = MagicMock(
                __aenter__=AsyncMock(return_value=session),
                __aexit__=AsyncMock(return_value=False),
            )
            with pytest.raises(ValueError, match="not found"):
                await recover_failed_job(99, factory)

    async def test_raises_when_wrong_job_type(self) -> None:
        """recover_failed_job must raise ValueError for non-player_info jobs."""
        session = _make_session()
        row = _make_job(status=ScrapeStatus.FAILED, fk_url_registry_id=1)
        row.job_type = "player_list"
        session.get.return_value = row
        factory = self._make_session_factory(session)

        with patch(_GET_SESSION) as mock_gs:
            mock_gs.return_value = MagicMock(
                __aenter__=AsyncMock(return_value=session),
                __aexit__=AsyncMock(return_value=False),
            )
            with pytest.raises(ValueError, match="job_type"):
                await recover_failed_job(1, factory)

    async def test_raises_when_job_not_failed(self) -> None:
        """recover_failed_job must raise ValueError when job is not in FAILED state."""
        session = _make_session()
        row = _make_job(status=ScrapeStatus.PENDING, fk_url_registry_id=1)
        session.get.return_value = row
        factory = self._make_session_factory(session)

        with patch(_GET_SESSION) as mock_gs:
            mock_gs.return_value = MagicMock(
                __aenter__=AsyncMock(return_value=session),
                __aexit__=AsyncMock(return_value=False),
            )
            with pytest.raises(ValueError, match="FAILED"):
                await recover_failed_job(1, factory)

    async def test_raises_when_no_url_registry_id(self) -> None:
        """recover_failed_job must raise ValueError when fk_url_registry_id is None."""
        session = _make_session()
        row = _make_job(status=ScrapeStatus.FAILED, fk_url_registry_id=None)
        session.get.return_value = row
        factory = self._make_session_factory(session)

        with patch(_GET_SESSION) as mock_gs:
            mock_gs.return_value = MagicMock(
                __aenter__=AsyncMock(return_value=session),
                __aexit__=AsyncMock(return_value=False),
            )
            with pytest.raises(ValueError, match="no associated"):
                await recover_failed_job(1, factory)

    async def test_raises_when_url_row_not_stale(self) -> None:
        """recover_failed_job must raise ValueError when URL row is not STALE."""
        session = _make_session()
        row = _make_job(status=ScrapeStatus.FAILED, fk_url_registry_id=10)
        session.get.return_value = row

        url_row = MagicMock()
        url_row.id = 10
        url_row.status = "ACTIVE"
        url_result = MagicMock()
        url_result.one_or_none.return_value = url_row
        session.execute.return_value = url_result

        factory = self._make_session_factory(session)

        with patch(_GET_SESSION) as mock_gs:
            mock_gs.return_value = MagicMock(
                __aenter__=AsyncMock(return_value=session),
                __aexit__=AsyncMock(return_value=False),
            )
            with pytest.raises(ValueError, match="STALE"):
                await recover_failed_job(1, factory)

    async def test_raises_when_url_row_not_found(self) -> None:
        """recover_failed_job must raise ValueError when URL row does not exist."""
        session = _make_session()
        row = _make_job(status=ScrapeStatus.FAILED, fk_url_registry_id=10)
        session.get.return_value = row

        url_result = MagicMock()
        url_result.one_or_none.return_value = None
        session.execute.return_value = url_result

        factory = self._make_session_factory(session)

        with patch(_GET_SESSION) as mock_gs:
            mock_gs.return_value = MagicMock(
                __aenter__=AsyncMock(return_value=session),
                __aexit__=AsyncMock(return_value=False),
            )
            with pytest.raises(ValueError, match="not found"):
                await recover_failed_job(1, factory)

    async def test_happy_path_resets_both_rows_to_pending(self) -> None:
        """recover_failed_job must reset queue row and url row to PENDING."""
        session = _make_session()
        queue_row = _make_job(
            job_id=1,
            status=ScrapeStatus.FAILED,
            fk_url_registry_id=10,
            retry_count=5,
        )
        queue_row.error_message = "some error"
        session.get.return_value = queue_row

        url_row = MagicMock()
        url_row.id = 10
        url_row.status = "STALE"
        url_result = MagicMock()
        url_result.one_or_none.return_value = url_row
        session.execute.return_value = url_result

        session.commit = AsyncMock()
        factory = self._make_session_factory(session)

        with patch(_GET_SESSION) as mock_gs, patch(
            "infrastructure.persistence.repositories.player_info_queue.BackendUrlRepository.recover_stale_url",
            new_callable=AsyncMock,
        ):
            mock_gs.return_value = MagicMock(
                __aenter__=AsyncMock(return_value=session),
                __aexit__=AsyncMock(return_value=False),
            )
            await recover_failed_job(1, factory)

        assert queue_row.status == ScrapeStatus.PENDING
        assert queue_row.retry_count == 0
        assert queue_row.error_message is None
        assert queue_row.locked_at is None
        session.commit.assert_called_once()


# ---------------------------------------------------------------------------
# _record_failure_with_retry helper tests
# ---------------------------------------------------------------------------


async def test_record_failure_with_retry_succeeds_on_second_attempt() -> None:
    """_record_failure_with_retry retries after a transient error and records once."""
    from unittest.mock import MagicMock, patch

    call_count = 0

    async def _flaky_record(*args, **kwargs) -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise OSError("transient db error")

    with patch(
        "scripts.scrape_player_info.record_job_failure",
        side_effect=_flaky_record,
    ):
        from scripts.scrape_player_info import _record_failure_with_retry

        await _record_failure_with_retry(
            42, "err", 5, MagicMock(), _max_attempts=3
        )

    assert call_count == 2


async def test_record_failure_with_retry_raises_after_exhaustion() -> None:
    """_record_failure_with_retry raises RuntimeError after all attempts fail."""
    from unittest.mock import MagicMock, patch

    async def _always_fail(*args, **kwargs) -> None:
        raise OSError("persistent db error")

    with patch(
        "scripts.scrape_player_info.record_job_failure",
        side_effect=_always_fail,
    ):
        from scripts.scrape_player_info import _record_failure_with_retry

        with pytest.raises(RuntimeError, match="FATAL"):
            await _record_failure_with_retry(
                42, "err", 5, MagicMock(), _max_attempts=3
            )
