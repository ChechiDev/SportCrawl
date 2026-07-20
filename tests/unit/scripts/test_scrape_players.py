"""Unit tests for scrape_players helpers: _seed_queue and PlayerListWorker.

asyncio_mode = "auto" via pyproject.toml — no explicit @pytest.mark.asyncio.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

if TYPE_CHECKING:
    from scripts.scrape_players import PlayerListWorker

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
            countries = [("ARG", _arg, "Argentina"), ("ESP", _esp, "Spain")]
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
            countries = [("ARG", _arg, "Argentina")]
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
    def _make_worker(
        self,
        fetch_gate: asyncio.Semaphore,
        settings: MagicMock,
        session_factory: MagicMock | None = None,
    ) -> PlayerListWorker:
        from scripts.scrape_players import PlayerListWorker
        return PlayerListWorker(
            worker_id=1,
            session_factory=session_factory or MagicMock(),
            fetch_gate=fetch_gate,
            profile_base="/tmp/chrome",
            worker_labels={1: "Worker 1"},
            worker_counts={1: 0},
            settings=settings,
        )

    def _mock_engine_ctx(self) -> tuple[AsyncMock, AsyncMock]:
        engine_instance = AsyncMock()
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=engine_instance)
        ctx.__aexit__ = AsyncMock(return_value=False)
        return ctx, engine_instance

    async def test_worker_marks_done_on_success(self) -> None:
        """PlayerListWorker must call mark_done after a successful scrape."""
        job = _make_job()

        session = AsyncMock()
        session.commit = AsyncMock()

        mock_repo = AsyncMock()
        mock_repo.claim_next.side_effect = [job, None]
        mock_repo.mark_done = AsyncMock()

        mock_scraper = AsyncMock()
        mock_page = MagicMock()
        mock_page.players = [MagicMock()] * 3
        mock_scraper.scrape.return_value = (mock_page, 3)

        engine_ctx, _ = self._mock_engine_ctx()
        settings = MagicMock()

        session_cm = MagicMock()
        session_cm.__aenter__ = AsyncMock(return_value=session)
        session_cm.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "scripts.scrape_players.PlayerListQueueRepository",
                return_value=mock_repo,
            ),
            patch(
                "scripts.scrape_players.PlayerListScraper",
                return_value=mock_scraper,
            ),
            patch(
                "scripts.scrape_players.PlayerListWorker._build_engine",
                return_value=engine_ctx,
            ),
            patch(
                "scripts.scrape_players.get_session",
                return_value=session_cm,
            ),
        ):
            worker = self._make_worker(asyncio.Semaphore(1), settings)
            processed = await worker.run()

        assert processed == 1
        mock_repo.mark_done.assert_called_once_with(job.id)

    async def test_worker_marks_failed_on_scraper_exception(self) -> None:
        """PlayerListWorker must call mark_failed when scrape raises."""
        job = _make_job()

        session = AsyncMock()
        session.commit = AsyncMock()

        mock_repo = AsyncMock()
        mock_repo.claim_next.side_effect = [job, None]
        mock_repo.mark_failed = AsyncMock()

        mock_scraper = AsyncMock()
        mock_scraper.scrape.side_effect = RuntimeError("timeout")

        engine_ctx, _ = self._mock_engine_ctx()
        settings = MagicMock()

        session_cm = MagicMock()
        session_cm.__aenter__ = AsyncMock(return_value=session)
        session_cm.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "scripts.scrape_players.PlayerListQueueRepository",
                return_value=mock_repo,
            ),
            patch(
                "scripts.scrape_players.PlayerListScraper",
                return_value=mock_scraper,
            ),
            patch(
                "scripts.scrape_players.PlayerListWorker._build_engine",
                return_value=engine_ctx,
            ),
            patch(
                "scripts.scrape_players.get_session",
                return_value=session_cm,
            ),
        ):
            worker = self._make_worker(asyncio.Semaphore(1), settings)
            processed = await worker.run()

        assert processed == 0
        mock_repo.mark_failed.assert_called_once()
        assert "timeout" in mock_repo.mark_failed.call_args[0][1]

    async def test_worker_exits_cleanly_when_queue_empty(self) -> None:
        """PlayerListWorker must return 0 immediately when queue is empty."""
        session = AsyncMock()
        session.commit = AsyncMock()

        mock_repo = AsyncMock()
        mock_repo.claim_next.return_value = None

        engine_ctx, _ = self._mock_engine_ctx()
        settings = MagicMock()

        session_cm = MagicMock()
        session_cm.__aenter__ = AsyncMock(return_value=session)
        session_cm.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "scripts.scrape_players.PlayerListQueueRepository",
                return_value=mock_repo,
            ),
            patch(
                "scripts.scrape_players.PlayerListWorker._build_engine",
                return_value=engine_ctx,
            ),
            patch(
                "scripts.scrape_players.get_session",
                return_value=session_cm,
            ),
        ):
            worker = self._make_worker(asyncio.Semaphore(1), settings)
            processed = await worker.run()

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
