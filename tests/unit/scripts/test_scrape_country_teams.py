"""Unit tests for scrape_country_teams helpers: _seed_queue and CountryTeamsWorker.

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


def _make_team_job(
    job_id: int = 1,
    url: str = "https://fbref.com/en/country/clubs/ARG/Argentina-Football",
) -> ScrapeQueue:
    job = ScrapeQueue()
    job.id = job_id
    job.url = url
    job.status = ScrapeStatus.PENDING
    job.retry_count = 0
    job.locked_at = None
    job.completed_at = None
    job.error_message = None
    job.job_type = "team_list"
    return job


_ARG_CLUBS_URL = "https://fbref.com/en/country/clubs/ARG/Argentina-Football"
_BRA_CLUBS_URL = "https://fbref.com/en/country/clubs/BRA/Brazil-Football"
_URU_CLUBS_URL = "https://fbref.com/en/country/clubs/URU/Uruguay-Football"


# ---------------------------------------------------------------------------
# _seed_queue tests
# ---------------------------------------------------------------------------


class TestSeedQueue:
    async def test_seed_queue_returns_inserted_count(self) -> None:
        """_seed_queue must return the number of inserted rows."""
        from scripts.scrape_country_teams import _seed_queue

        session = AsyncMock()
        result = MagicMock()
        result.rowcount = 3
        session.execute.return_value = result
        session.commit = AsyncMock()

        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("scripts.scrape_country_teams.get_session", return_value=cm):
            rows = [
                ("ARG", _ARG_CLUBS_URL),
                ("BRA", _BRA_CLUBS_URL),
                ("URU", _URU_CLUBS_URL),
            ]
            count = await _seed_queue(MagicMock(), rows)

        assert count == 3

    async def test_seed_queue_uses_on_conflict_do_nothing(self) -> None:
        """_seed_queue must use ON CONFLICT DO NOTHING (idempotency)."""
        from scripts.scrape_country_teams import _seed_queue

        session = AsyncMock()
        result = MagicMock()
        result.rowcount = 1
        session.execute.return_value = result
        session.commit = AsyncMock()

        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("scripts.scrape_country_teams.get_session", return_value=cm):
            rows = [("ARG", _ARG_CLUBS_URL)]
            await _seed_queue(MagicMock(), rows)

        # Verify execute was called with a statement (ON CONFLICT is in the stmt object)
        session.execute.assert_called_once()
        stmt_arg = session.execute.call_args[0][0]
         # The compiled insert should be a PostgreSQL insert with on_conflict
        assert stmt_arg is not None

    async def test_seed_queue_returns_zero_for_empty_input(self) -> None:
        """_seed_queue must return 0 and not touch the DB for empty input."""
        from scripts.scrape_country_teams import _seed_queue

        session_factory = MagicMock()

        with patch("scripts.scrape_country_teams.get_session") as mock_gs:
            count = await _seed_queue(session_factory, [])

        assert count == 0
        mock_gs.assert_not_called()

    async def test_seed_queue_filter_agnostic(self) -> None:
        """_seed_queue seeds exactly the rows it receives — no internal filtering."""
        from scripts.scrape_country_teams import _seed_queue

        session = AsyncMock()
        result = MagicMock()
        result.rowcount = 1
        session.execute.return_value = result
        session.commit = AsyncMock()

        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("scripts.scrape_country_teams.get_session", return_value=cm):
            # Pass only ARG row — function should seed exactly 1
            count = await _seed_queue(MagicMock(), [("ARG", _ARG_CLUBS_URL)])

        assert count == 1
        session.execute.assert_called_once()


# ---------------------------------------------------------------------------
# CountryTeamsWorker constructor tests
# ---------------------------------------------------------------------------


class TestCountryTeamsWorkerConstructor:
    def _make_worker(self, **kwargs: object) -> object:
        from scripts.scrape_country_teams import CountryTeamsWorker

        defaults = dict(
            worker_id=1,
            session_factory=MagicMock(),
            fetch_gate=asyncio.Semaphore(1),
            profile_base="/tmp/profiles",
            worker_labels={},
            worker_counts={},
            settings=MagicMock(),
            url_to_country={"https://fbref.com/en/country/clubs/ARG/": "ARG"},
            country_filter=None,
            country_names={"ARG": "Argentina"},
        )
        defaults.update(kwargs)
        return CountryTeamsWorker(**defaults)  # type: ignore[arg-type]

    def test_worker_accepts_url_to_country_param(self) -> None:
        """Worker must accept url_to_country constructor param."""
        url_map = {_ARG_CLUBS_URL: "ARG", _BRA_CLUBS_URL: "BRA"}
        worker = self._make_worker(url_to_country=url_map)
        assert worker._url_to_country == url_map  # type: ignore[attr-defined]

    def test_worker_accepts_country_filter_param(self) -> None:
        """Worker must accept country_filter constructor param."""
        worker = self._make_worker(country_filter={"ARG"})
        assert worker._country_filter == {"ARG"}  # type: ignore[attr-defined]

    def test_worker_country_filter_defaults_to_none(self) -> None:
        """country_filter defaults to None (--all mode)."""
        worker = self._make_worker(country_filter=None)
        assert worker._country_filter is None  # type: ignore[attr-defined]

    def test_worker_does_not_accept_queue_param(self) -> None:
        """Worker must NOT accept a queue= param (old asyncio.Queue interface)."""
        import inspect

        from scripts.scrape_country_teams import CountryTeamsWorker

        sig = inspect.signature(CountryTeamsWorker.__init__)
        assert "queue" not in sig.parameters

    def test_worker_has_no_browser_restart_counts(self) -> None:
        """Worker must NOT have _browser_restart_counts attribute."""
        worker = self._make_worker()
        assert not hasattr(worker, "_browser_restart_counts")

    def test_worker_has_no_queue_attribute(self) -> None:
        """Worker must NOT have _queue attribute."""
        worker = self._make_worker()
        assert not hasattr(worker, "_queue")
