"""Integration test for the player_info scraping worker.

Verifies end-to-end behaviour using a real Postgres testcontainer and a
mocked PydollEngine / PlayerInfoScraper:
- Seeds one scrape_queue row (job_type='player_info')
- Calls the worker coroutine with the mocked scraper
- Asserts tbl_player_info row was inserted
- Asserts scrape_queue row is marked DONE

The test is intentionally narrow: it validates the worker orchestration
layer without exercising the real browser or FBRef network.
"""

from __future__ import annotations

import asyncio
from datetime import date
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from domains.player_info.models import PlayerInfoPage, PlayerInfoRawData
from infrastructure.persistence.models.scrape_queue import ScrapeQueue, ScrapeStatus
from infrastructure.persistence.models.shared.player import Player
from scripts.scrape_player_info import _worker

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PLAYER_ID = "abc12345"
_PLAYER_URL = "https://fbref.com/en/players/abc12345/Test-Player"

_FIXED_RAW = PlayerInfoRawData(
    player_id=_PLAYER_ID,
    fk_country_birth=None,
    city_name="Buenos Aires",
    player_born=date(1990, 5, 20),
    player_height=180,
    player_weight=75,
    position_1="FW",
    position_2=None,
    position_3=None,
    player_foot="Right",
    player_wages=None,
    player_expires=None,
    player_info_url=_PLAYER_URL,
    photo_url=None,
)

_FIXED_PAGE = PlayerInfoPage(players=[_FIXED_RAW])


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(loop_scope="function")
async def session_factory_with_player(
    _integration_db_url,  # type: ignore[no-untyped-def]
):
    """Return an async_sessionmaker and a seeded tbl_players + scrape_queue row.

    Seeds:
    - One tbl_players row (required by FK on tbl_player_info.player_id)
    - One scrape_queue row with job_type='player_info', status=PENDING
    """
    engine = create_async_engine(_integration_db_url, echo=False)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        async with session.begin():
            # Insert player so FK constraint on tbl_player_info is satisfied
            player = Player(
                player_id=_PLAYER_ID,
                full_name="Test Player",
                career_start=2010,
                career_end=2023,
                player_url=_PLAYER_URL,
                fk_country=None,
            )
            session.add(player)

            # Insert scrape_queue row
            job = ScrapeQueue(
                url=_PLAYER_URL,
                domain="fbref.com",
                status=ScrapeStatus.PENDING,
                job_type="player_info",
            )
            session.add(job)

    yield factory

    # Cleanup: remove test data to avoid polluting other tests
    async with factory() as session:
        async with session.begin():
            await session.execute(
                text(
                    "DELETE FROM sch_infra.scrape_queue WHERE url = :url"
                ),
                {"url": _PLAYER_URL},
            )
            await session.execute(
                text(
                    "DELETE FROM sch_shared.tbl_player_info WHERE player_id = :pid"
                ),
                {"pid": _PLAYER_ID},
            )
            await session.execute(
                text(
                    "DELETE FROM sch_shared.tbl_players WHERE player_id = :pid"
                ),
                {"pid": _PLAYER_ID},
            )

    await engine.dispose()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_worker_inserts_player_info_and_marks_done(
    session_factory_with_player: async_sessionmaker,
) -> None:
    """Worker processes one job: tbl_player_info inserted, queue row DONE."""
    factory = session_factory_with_player

    mock_page = _FIXED_PAGE

    with (
        patch(
            "scripts.scrape_player_info.PydollEngine",
        ) as MockEngine,
        patch(
            "scripts.scrape_player_info.PlayerInfoScraper",
        ) as MockScraper,
    ):
        # Configure engine context manager
        mock_engine_instance = AsyncMock()
        MockEngine.return_value.__aenter__ = AsyncMock(
            return_value=mock_engine_instance
        )
        MockEngine.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_engine_instance.fetch = AsyncMock(return_value="<html></html>")

        # Configure scraper
        mock_scraper_instance = AsyncMock()
        MockScraper.return_value = mock_scraper_instance
        mock_scraper_instance.parse = AsyncMock(return_value=mock_page)

        processed = await _worker(
            worker_id=1,
            session_factory=factory,
            fetch_gate=asyncio.Semaphore(1),
            chrome_profile_base="/tmp/test-chrome",
            position_cache={},
            valid_countries=frozenset(),
            worker_status={},
        )

    assert processed == 1

    # Verify tbl_player_info row was inserted
    async with factory() as session:
        result = await session.execute(
            text(
                "SELECT player_id FROM sch_shared.tbl_player_info"
                " WHERE player_id = :pid"
            ),
            {"pid": _PLAYER_ID},
        )
        row = result.fetchone()
    assert row is not None, "Expected tbl_player_info row was not inserted"

    # Verify scrape_queue row is DONE
    async with factory() as session:
        result = await session.execute(
            text(
                "SELECT status FROM sch_infra.scrape_queue"
                " WHERE url = :url"
            ),
            {"url": _PLAYER_URL},
        )
        status_row = result.fetchone()
    assert status_row is not None
    assert status_row[0] == "DONE", f"Expected DONE but got {status_row[0]}"
