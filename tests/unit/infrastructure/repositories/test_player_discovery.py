"""Unit tests for PlayerDiscoveryRepository.

All database calls are mocked via AsyncMock session + patched pg_insert.
asyncio_mode = "auto" via pyproject.toml — no explicit @pytest.mark.asyncio.
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

from domains.player.models import PlayerRawData
from infrastructure.persistence.repositories.player_discovery import (
    PlayerDiscoveryRepository,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_player(player_id: str) -> PlayerRawData:
    return PlayerRawData(
        player_id=player_id,
        full_name=f"Player {player_id}",
        career_start=2000,
        career_end=2000,
        player_url=f"https://fbref.com/en/players/{player_id}/Player-{player_id}",
    )


def _make_session() -> AsyncMock:
    """Return an AsyncMock session whose execute() returns a usable result."""
    session = AsyncMock()
    # scalars().all() returns empty list by default (for SELECT id FROM scrape_queue)
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    session.execute.return_value = result
    return session


@contextmanager
def _pg_insert_mock():
    """Context manager that patches pg_insert and yields a configured stmt mock.

    The stmt mock chains on_conflict_do_nothing() and returning() back to itself
    so fluent call chains in the repository work without raising AttributeError.
    """
    with patch(
        "infrastructure.persistence.repositories.player_discovery.pg_insert"
    ) as mock_pg_insert:
        stmt_mock = MagicMock()
        stmt_mock.on_conflict_do_nothing.return_value = stmt_mock
        stmt_mock.on_conflict_do_update.return_value = stmt_mock
        stmt_mock.returning.return_value = stmt_mock
        mock_pg_insert.return_value = stmt_mock
        yield mock_pg_insert


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPlayerDiscoveryRepositoryBulkEnqueue:
    """Tests for PlayerDiscoveryRepository.bulk_enqueue()."""

    async def test_bulk_enqueue_calls_pg_insert_for_player(self) -> None:
        """bulk_enqueue must issue pg_insert for Player ON CONFLICT DO NOTHING."""
        session = _make_session()
        rows = [_make_player("aabbccdd")]

        with _pg_insert_mock() as mock_pg_insert:
            repo = PlayerDiscoveryRepository(session)
            await repo.bulk_enqueue(rows, "ESP")

        from infrastructure.persistence.models.shared.player import Player

        call_tables = [c.args[0] for c in mock_pg_insert.call_args_list]
        assert Player in call_tables

    async def test_bulk_enqueue_calls_pg_insert_for_scrape_queue(self) -> None:
        """bulk_enqueue must issue a pg_insert for ScrapeQueue ON CONFLICT(url)."""
        session = _make_session()
        rows = [_make_player("aabbccdd")]

        with _pg_insert_mock() as mock_pg_insert:
            repo = PlayerDiscoveryRepository(session)
            await repo.bulk_enqueue(rows, "ESP")

        from infrastructure.persistence.models.scrape_queue import ScrapeQueue

        call_tables = [c.args[0] for c in mock_pg_insert.call_args_list]
        assert ScrapeQueue in call_tables

    async def test_bulk_enqueue_calls_pg_insert_for_player_queue_ref(self) -> None:
        """bulk_enqueue must issue a pg_insert for PlayerQueueRef."""
        session = _make_session()
        rows = [_make_player("aabbccdd")]

        # Simulate scrape_queue returning an id so PlayerQueueRef can be inserted
        sq_result = MagicMock()
        sq_result.scalars.return_value.all.return_value = [1]
        session.execute.return_value = sq_result

        with _pg_insert_mock() as mock_pg_insert:
            repo = PlayerDiscoveryRepository(session)
            await repo.bulk_enqueue(rows, "ESP")

        from infrastructure.persistence.models.infra.player_queue_ref import (
            PlayerQueueRef,
        )

        call_tables = [c.args[0] for c in mock_pg_insert.call_args_list]
        assert PlayerQueueRef in call_tables

    async def test_bulk_enqueue_returns_player_row_count(self) -> None:
        """bulk_enqueue must return len(rows) — the number of players processed."""
        session = _make_session()
        rows = [_make_player("aa000001"), _make_player("bb000002")]

        with _pg_insert_mock():
            repo = PlayerDiscoveryRepository(session)
            result = await repo.bulk_enqueue(rows, "ARG")

        assert result == 2

    async def test_bulk_enqueue_second_call_does_not_raise(self) -> None:
        """Calling bulk_enqueue twice with the same rows must not raise (idempotent)."""
        session = _make_session()
        rows = [_make_player("aabbccdd")]

        with _pg_insert_mock() as mock_pg_insert:
            repo = PlayerDiscoveryRepository(session)
            result_first = await repo.bulk_enqueue(rows, "ESP")
            # Second call with same data — must not raise
            result_second = await repo.bulk_enqueue(rows, "ESP")

        # Both calls return the same row count (idempotent result)
        assert result_first == result_second == 1
        # pg_insert was called for both invocations — call count is 2× that of a single call
        assert mock_pg_insert.call_count % 2 == 0
        assert mock_pg_insert.call_count >= 4  # at least Player + ScrapeQueue × 2 calls
