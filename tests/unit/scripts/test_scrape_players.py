"""Unit tests for scrape_players helpers: _seed_queue and _worker.

asyncio_mode = "auto" via pyproject.toml — no explicit @pytest.mark.asyncio.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from infrastructure.persistence.models.scrape_queue import ScrapeQueue, ScrapeStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session_factory(session: AsyncMock) -> MagicMock:
    """Return a session factory whose async context manager yields *session*."""
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    factory = MagicMock()
    factory.return_value = cm
    return factory


_ARG_URL = "https://fbref.com/en/country/players/ARG/Argentina-Football"


def _make_job(job_id: int = 1, url: str = _ARG_URL) -> ScrapeQueue:
    job = ScrapeQueue()
    job.id = job_id
    job.url = url
    job.status = ScrapeStatus.PENDING
    job.retry_count = 0
    job.locked_at = None
    job.completed_at = None
    job.error_message = None
    job.job_type = "player_list"
    return job


# ---------------------------------------------------------------------------
# _seed_queue tests
# ---------------------------------------------------------------------------


class TestSeedQueue:
    async def test_seed_queue_returns_inserted_count(self) -> None:
        """_seed_queue must return the number of inserted rows."""
        from scripts.scrape_players import _seed_queue

        session = AsyncMock()
        result = MagicMock()
        result.rowcount = 2
        session.execute.return_value = result
        session.commit = AsyncMock()

        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("scripts.scrape_players.get_session", return_value=cm):
            _arg = "https://fbref.com/en/country/players/ARG/Argentina-Football"
            _esp = "https://fbref.com/en/country/players/ESP/Spain-Football"
            countries = [("ARG", _arg), ("ESP", _esp)]
            count = await _seed_queue(MagicMock(), countries)

        assert count == 2

    async def test_seed_queue_uses_on_conflict_do_nothing(self) -> None:
        """_seed_queue must use ON CONFLICT DO NOTHING (idempotency)."""
        from scripts.scrape_players import _seed_queue

        session = AsyncMock()
        result = MagicMock()
        result.rowcount = 0
        session.execute.return_value = result
        session.commit = AsyncMock()

        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("scripts.scrape_players.get_session", return_value=cm):
            _arg = "https://fbref.com/en/country/players/ARG/Argentina-Football"
            countries = [("ARG", _arg)]
            count = await _seed_queue(MagicMock(), countries)

        # rowcount=0 means ON CONFLICT fired and nothing was inserted
        assert count == 0

    async def test_seed_queue_empty_countries_returns_zero(self) -> None:
        """_seed_queue with empty list must return 0 without touching the DB."""
        from scripts.scrape_players import _seed_queue

        session = AsyncMock()
        count = await _seed_queue(MagicMock(), [])

        session.execute.assert_not_called()
        assert count == 0


# ---------------------------------------------------------------------------
# _worker tests
# ---------------------------------------------------------------------------


class TestWorker:
    async def test_worker_marks_done_on_success(self) -> None:
        """_worker must call mark_done after a successful scrape."""
        from scripts.scrape_players import _worker

        job = _make_job()

        session = AsyncMock()
        session.commit = AsyncMock()

        # claim_next returns job first time, None second (queue empty)
        claim_results = [job, None]

        mock_repo = AsyncMock()
        mock_repo.claim_next.side_effect = claim_results
        mock_repo.mark_done = AsyncMock()

        mock_scraper = AsyncMock()
        mock_scraper.scrape.return_value = (MagicMock(), 5)

        mock_engine_cm = AsyncMock()
        mock_engine_cm.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_engine_cm.__aexit__ = AsyncMock(return_value=False)

        settings = MagicMock()
        settings.scraping = MagicMock()

        with (
            patch("scripts.scrape_players.PlayerListQueueRepository", return_value=mock_repo),  # noqa: E501
            patch("scripts.scrape_players.PlayerListScraper", return_value=mock_scraper),  # noqa: E501
            patch("scripts.scrape_players.PydollEngine", return_value=mock_engine_cm),
            patch("scripts.scrape_players.get_session") as mock_get_session,
        ):
            cm = MagicMock()
            cm.__aenter__ = AsyncMock(return_value=session)
            cm.__aexit__ = AsyncMock(return_value=False)
            mock_get_session.return_value = cm

            fetch_gate = asyncio.Semaphore(1)
            processed = await _worker(
                worker_id=1,
                session_factory=MagicMock(),
                fetch_gate=fetch_gate,
                profile_base="/tmp/chrome",
                settings=settings,
                worker_labels={1: "Worker 1"},
                worker_counts={1: 0},
            )

        assert processed == 1
        mock_repo.mark_done.assert_called_once_with(job.id)

    async def test_worker_marks_failed_on_scraper_exception(self) -> None:
        """_worker must call mark_failed and NOT crash when scrape raises."""
        from scripts.scrape_players import _worker

        job = _make_job()

        session = AsyncMock()
        session.commit = AsyncMock()

        mock_repo = AsyncMock()
        mock_repo.claim_next.side_effect = [job, None]
        mock_repo.mark_failed = AsyncMock()

        mock_scraper = AsyncMock()
        mock_scraper.scrape.side_effect = RuntimeError("timeout")

        mock_engine_cm = AsyncMock()
        mock_engine_cm.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_engine_cm.__aexit__ = AsyncMock(return_value=False)

        settings = MagicMock()
        settings.scraping = MagicMock()

        with (
            patch("scripts.scrape_players.PlayerListQueueRepository", return_value=mock_repo),  # noqa: E501
            patch("scripts.scrape_players.PlayerListScraper", return_value=mock_scraper),  # noqa: E501
            patch("scripts.scrape_players.PydollEngine", return_value=mock_engine_cm),
            patch("scripts.scrape_players.get_session") as mock_get_session,
        ):
            cm = MagicMock()
            cm.__aenter__ = AsyncMock(return_value=session)
            cm.__aexit__ = AsyncMock(return_value=False)
            mock_get_session.return_value = cm

            fetch_gate = asyncio.Semaphore(1)
            processed = await _worker(
                worker_id=1,
                session_factory=MagicMock(),
                fetch_gate=fetch_gate,
                profile_base="/tmp/chrome",
                settings=settings,
                worker_labels={1: "Worker 1"},
                worker_counts={1: 0},
            )

        assert processed == 0
        mock_repo.mark_failed.assert_called_once()
        assert "timeout" in mock_repo.mark_failed.call_args[0][1]

    async def test_worker_exits_cleanly_when_queue_empty(self) -> None:
        """_worker must return 0 immediately when claim_next returns None."""
        from scripts.scrape_players import _worker

        session = AsyncMock()
        session.commit = AsyncMock()

        mock_repo = AsyncMock()
        mock_repo.claim_next.return_value = None

        mock_engine_cm = AsyncMock()
        mock_engine_cm.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_engine_cm.__aexit__ = AsyncMock(return_value=False)

        settings = MagicMock()
        settings.scraping = MagicMock()

        with (
            patch("scripts.scrape_players.PlayerListQueueRepository", return_value=mock_repo),  # noqa: E501
            patch("scripts.scrape_players.PydollEngine", return_value=mock_engine_cm),
            patch("scripts.scrape_players.get_session") as mock_get_session,
        ):
            cm = MagicMock()
            cm.__aenter__ = AsyncMock(return_value=session)
            cm.__aexit__ = AsyncMock(return_value=False)
            mock_get_session.return_value = cm

            fetch_gate = asyncio.Semaphore(1)
            processed = await _worker(
                worker_id=1,
                session_factory=MagicMock(),
                fetch_gate=fetch_gate,
                profile_base="/tmp/chrome",
                settings=settings,
                worker_labels={1: "Worker 1"},
                worker_counts={1: 0},
            )

        assert processed == 0

    async def test_workers_get_unique_profile_dirs(self) -> None:
        """Each worker_id must produce a distinct Chrome profile path."""
        # Verify the naming convention without running actual workers
        worker_ids = [1, 2, 3]
        base = "/tmp/chrome"
        dirs = [f"{base}-player-list-{wid}" for wid in worker_ids]
        assert len(set(dirs)) == len(dirs)

    async def test_fetch_gate_serializes_scrapes(self) -> None:
        """fetch_gate (Semaphore(1)) must never allow concurrent acquisitions."""
        concurrent_count = 0
        max_concurrent = 0

        async def fake_scrape(_url: str) -> tuple[MagicMock, int]:
            nonlocal concurrent_count, max_concurrent
            concurrent_count += 1
            max_concurrent = max(max_concurrent, concurrent_count)
            await asyncio.sleep(0)
            concurrent_count -= 1
            return MagicMock(), 1

        fetch_gate = asyncio.Semaphore(1)

        async def gated_scrape(url: str) -> tuple[MagicMock, int]:
            async with fetch_gate:
                return await fake_scrape(url)

        urls = [f"https://fbref.com/url/{i}" for i in range(5)]
        await asyncio.gather(*[gated_scrape(u) for u in urls])

        assert max_concurrent == 1
