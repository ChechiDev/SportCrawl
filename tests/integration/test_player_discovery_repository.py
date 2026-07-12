"""Integration tests for PlayerDiscoveryRepository.

Covers:
- bulk_enqueue persists rows across tbl_players, scrape_queue, player_queue_ref
- v_player_scrape_progress reports correct pending count after bulk_enqueue
- bulk_enqueue is idempotent — repeated calls produce no duplicates
- Player positions cascade-delete when the parent player is deleted

All tests use the async_session fixture (function-scoped, rolled back after each
test). No mocks — real Postgres via testcontainers.
"""

from __future__ import annotations

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from domains.player.models import PlayerRawData
from infrastructure.persistence.models.football.player_queue_ref import PlayerQueueRef
from infrastructure.persistence.models.scrape_queue import ScrapeQueue, ScrapeStatus
from infrastructure.persistence.models.shared.player import Player
from infrastructure.persistence.models.shared.player_position import PlayerPosition
from infrastructure.persistence.repositories.player_discovery import (
    PlayerDiscoveryRepository,
)

# ---------------------------------------------------------------------------
# Test data helpers
# ---------------------------------------------------------------------------

_COUNTRY_ID = "ESP"


def _make_player(
    player_id: str,
    display_name: str,
    *,
    positions: list[str] | None = None,
) -> PlayerRawData:
    """Return a minimal PlayerRawData for testing."""
    return PlayerRawData(
        player_id=player_id,
        display_name=display_name,
        full_name=None,
        career_start=2010,
        career_end=None,
        positions=positions or ["FW"],
        player_url=f"https://fbref.com/en/players/{player_id}/Player-Name",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBulkEnqueuePersistsPlayers:
    async def test_bulk_enqueue_persists_players(
        self, async_session: AsyncSession
    ) -> None:
        """bulk_enqueue inserts rows into tbl_players, scrape_queue, and queue_ref."""
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

        # Verify scrape_queue has PENDING entries for the player URLs
        urls = [r.player_url for r in rows]
        sq_result = await async_session.execute(
            select(ScrapeQueue).where(ScrapeQueue.url.in_(urls))
        )
        sq_rows = sq_result.scalars().all()
        assert len(sq_rows) == 3
        assert all(r.status == ScrapeStatus.PENDING for r in sq_rows)

        # Verify player_queue_ref links
        queue_ids = [r.id for r in sq_rows]
        ref_result = await async_session.execute(
            select(PlayerQueueRef).where(PlayerQueueRef.queue_id.in_(queue_ids))
        )
        refs = ref_result.scalars().all()
        assert len(refs) == 3

    async def test_bulk_enqueue_view_pending_count(
        self, async_session: AsyncSession
    ) -> None:
        """v_player_scrape_progress shows pending=3 after bulk_enqueue of 3 players."""
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
                "SELECT pending FROM sch_football.v_player_scrape_progress"
                " WHERE country_id = :cid"
            ),
            {"cid": _COUNTRY_ID},
        )
        row = result.fetchone()
        assert row is not None
        assert row[0] == 3


class TestBulkEnqueueIdempotent:
    async def test_bulk_enqueue_idempotent(
        self, async_session: AsyncSession
    ) -> None:
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
            select(Player).where(
                Player.player_id.in_(["11111111", "22222222"])
            )
        )
        players = player_result.scalars().all()
        assert len(players) == 2

        # scrape_queue — no duplicates
        urls = [r.player_url for r in rows]
        sq_result = await async_session.execute(
            select(ScrapeQueue).where(ScrapeQueue.url.in_(urls))
        )
        sq_rows = sq_result.scalars().all()
        assert len(sq_rows) == 2

        # player_queue_ref — no duplicates
        queue_ids = [r.id for r in sq_rows]
        ref_result = await async_session.execute(
            select(PlayerQueueRef).where(PlayerQueueRef.queue_id.in_(queue_ids))
        )
        refs = ref_result.scalars().all()
        assert len(refs) == 2

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
                "SELECT pending FROM sch_football.v_player_scrape_progress"
                " WHERE country_id = :cid"
            ),
            {"cid": _COUNTRY_ID},
        )
        row = result.fetchone()
        assert row is not None
        # Only 2 unique players enqueued — pending count must not be 4
        assert row[0] == 2


class TestBulkEnqueueCascadeDelete:
    async def test_bulk_enqueue_positions_cascade_delete(
        self, async_session: AsyncSession
    ) -> None:
        """Deleting a player cascades to tbl_player_positions."""
        repo = PlayerDiscoveryRepository(async_session)
        player_id = "55555555"
        rows = [
            _make_player(
                player_id, "Player Five", positions=["FW", "MF"]
            )
        ]

        await repo.bulk_enqueue(rows, _COUNTRY_ID)
        await async_session.flush()

        # Verify positions were inserted
        pos_result = await async_session.execute(
            select(PlayerPosition).where(
                PlayerPosition.fk_player == player_id
            )
        )
        positions = pos_result.scalars().all()
        assert len(positions) == 2

        # Delete the player — should cascade to positions
        player = await async_session.get(Player, player_id)
        assert player is not None
        await async_session.delete(player)
        await async_session.flush()

        # Positions should be gone
        pos_after = await async_session.execute(
            select(PlayerPosition).where(
                PlayerPosition.fk_player == player_id
            )
        )
        assert len(pos_after.scalars().all()) == 0
