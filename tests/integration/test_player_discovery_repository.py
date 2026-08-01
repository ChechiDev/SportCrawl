"""Integration tests for PlayerDiscoveryRepository.

Covers:
- bulk_enqueue persists rows into tbl_players and tbl_player_urls
- v_player_scrape_progress reflects correct total_urls after bulk_enqueue
- bulk_enqueue is idempotent — repeated calls produce no duplicates

All tests use the async_session fixture (function-scoped, rolled back after each
test). No mocks — real Postgres via testcontainers.
"""

from __future__ import annotations

import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from domains.player.models import PlayerRawData
from infrastructure.persistence.models.backend.player_urls import PlayerUrl
from infrastructure.persistence.models.infra.player_discovery_batch import (
    PlayerDiscoveryBatch,
)
from infrastructure.persistence.models.shared.player import Player
from infrastructure.persistence.repositories.player_discovery import (
    PlayerDiscoveryRepository,
)

# ---------------------------------------------------------------------------
# Test data helpers
# ---------------------------------------------------------------------------

_COUNTRY_ID = "ESP"


def _make_player(
    player_id: str,
    full_name: str,
) -> PlayerRawData:
    """Return a minimal PlayerRawData for testing."""
    return PlayerRawData(
        player_id=player_id,
        full_name=full_name,
        career_start=2010,
        career_end=2023,
        player_url=f"https://fbref.com/en/players/{player_id}/Player-Name",
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(autouse=True, loop_scope="function")
async def _seed_country(async_session: AsyncSession) -> None:
    """Insert the ESP country row so tbl_players FK is satisfied."""
    await async_session.execute(
        text(
            "INSERT INTO sch_fbref_shared.tbl_countries"
            " (country_id, country_name)"
            " VALUES (:cid, 'Spain')"
            " ON CONFLICT DO NOTHING"
        ),
        {"cid": _COUNTRY_ID},
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBulkEnqueuePersistsPlayers:
    async def test_bulk_enqueue_persists_players(
        self, async_session: AsyncSession
    ) -> None:
        """bulk_enqueue inserts rows into tbl_players and tbl_player_urls."""
        repo = PlayerDiscoveryRepository(async_session)
        rows = [
            _make_player("aaaaaaaa", "Player Alpha"),
            _make_player("bbbbbbbb", "Player Beta"),
            _make_player("cccccccc", "Player Gamma"),
        ]

        count = await repo.bulk_enqueue(rows, _COUNTRY_ID)
        await async_session.flush()

        assert count == 3

        # Verify tbl_players
        player_result = await async_session.execute(
            select(Player).where(
                Player.player_id.in_(["aaaaaaaa", "bbbbbbbb", "cccccccc"])
            )
        )
        players = player_result.scalars().all()
        assert len(players) == 3

        # Verify tbl_player_urls has backend scheduling rows
        url_result = await async_session.execute(
            select(PlayerUrl).where(
                PlayerUrl.fk_player.in_(["aaaaaaaa", "bbbbbbbb", "cccccccc"])
            )
        )
        url_rows = url_result.scalars().all()
        assert len(url_rows) == 3

        # Verify PlayerDiscoveryBatch recorded the country
        batch_result = await async_session.execute(
            select(PlayerDiscoveryBatch).where(
                PlayerDiscoveryBatch.country_id == _COUNTRY_ID
            )
        )
        batch = batch_result.scalar_one()
        assert batch.total_urls == 3

    async def test_bulk_enqueue_view_pending_count(
        self, async_session: AsyncSession
    ) -> None:
        """v_player_scrape_progress shows total_urls=3 after bulk_enqueue."""
        repo = PlayerDiscoveryRepository(async_session)
        rows = [
            _make_player("dddddddd", "Player Delta"),
            _make_player("eeeeeeee", "Player Epsilon"),
            _make_player("ffffffff", "Player Zeta"),
        ]

        await repo.bulk_enqueue(rows, _COUNTRY_ID)
        await async_session.flush()

        result = await async_session.execute(
            text(
                "SELECT total_urls FROM sch_fbref_football.v_player_scrape_progress"
                " WHERE country_id = :cid"
            ),
            {"cid": _COUNTRY_ID},
        )
        row = result.fetchone()
        assert row is not None
        assert row[0] == 3


class TestBulkEnqueueIdempotent:
    async def test_bulk_enqueue_idempotent(self, async_session: AsyncSession) -> None:
        """Calling bulk_enqueue twice with same rows produces no duplicates."""
        repo = PlayerDiscoveryRepository(async_session)
        rows = [
            _make_player("11111111", "Player One"),
            _make_player("22222222", "Player Two"),
        ]

        await repo.bulk_enqueue(rows, _COUNTRY_ID)
        await async_session.flush()
        await repo.bulk_enqueue(rows, _COUNTRY_ID)
        await async_session.flush()

        # tbl_players — no duplicates
        player_result = await async_session.execute(
            select(Player).where(Player.player_id.in_(["11111111", "22222222"]))
        )
        players = player_result.scalars().all()
        assert len(players) == 2

        # tbl_player_urls — no duplicates
        url_result = await async_session.execute(
            select(PlayerUrl).where(
                PlayerUrl.fk_player.in_(["11111111", "22222222"])
            )
        )
        url_rows = url_result.scalars().all()
        assert len(url_rows) == 2

    async def test_bulk_enqueue_idempotent_view_no_double_count(
        self, async_session: AsyncSession
    ) -> None:
        """View shows correct counts — no double-counting on second bulk_enqueue."""
        repo = PlayerDiscoveryRepository(async_session)
        rows = [
            _make_player("33333333", "Player Three"),
            _make_player("44444444", "Player Four"),
        ]

        await repo.bulk_enqueue(rows, _COUNTRY_ID)
        await async_session.flush()
        await repo.bulk_enqueue(rows, _COUNTRY_ID)
        await async_session.flush()

        result = await async_session.execute(
            text(
                "SELECT total_urls FROM sch_fbref_football.v_player_scrape_progress"
                " WHERE country_id = :cid"
            ),
            {"cid": _COUNTRY_ID},
        )
        row = result.fetchone()
        assert row is not None
        # Only 2 unique players enqueued — total_urls must not be 4
        assert row[0] == 2
