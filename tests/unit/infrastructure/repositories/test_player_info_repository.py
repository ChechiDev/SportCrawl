"""Unit tests for PlayerInfoRepository.

All database calls are mocked via AsyncMock session + patched pg_insert.
asyncio_mode = "auto" via pyproject.toml — no explicit @pytest.mark.asyncio.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

from domains.player_info.models import PlayerInfoRawData
from infrastructure.persistence.repositories.player_info import PlayerInfoRepository

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_PLAYER_ID = "d70ce98e"
_PLAYER_URL = "https://fbref.com/en/players/d70ce98e/Lionel-Messi"


def _make_raw(
    player_id: str = _PLAYER_ID,
    position_1: str | None = "FW",
    position_2: str | None = None,
    position_3: str | None = None,
    photo_url: str | None = "https://cdn.fbref.com/images/d70ce98e.jpg",
) -> PlayerInfoRawData:
    return PlayerInfoRawData(
        player_id=player_id,
        player_info_url=_PLAYER_URL,
        player_born=date(1987, 6, 24),
        player_height=170,
        player_weight=72,
        player_foot="Left",
        position_1=position_1,
        position_2=position_2,
        position_3=position_3,
        photo_url=photo_url,
    )


def _make_session() -> AsyncMock:
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.first.return_value = None
    result.scalar_one_or_none.return_value = None
    session.execute.return_value = result
    return session


@contextmanager
def _pg_insert_mock(module_path: str):
    with patch(f"{module_path}.pg_insert") as mock_pg_insert:
        stmt_mock = MagicMock()
        stmt_mock.values.return_value = stmt_mock
        stmt_mock.on_conflict_do_nothing.return_value = stmt_mock
        stmt_mock.on_conflict_do_update.return_value = stmt_mock
        stmt_mock.returning.return_value = stmt_mock
        stmt_mock.excluded = MagicMock()
        mock_pg_insert.return_value = stmt_mock
        yield mock_pg_insert


_REPO_MODULE = "infrastructure.persistence.repositories.player_info"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestUpsertPlayerInfo:
    async def test_upsert_player_info_inserts_new_row(self) -> None:
        """upsert_player_info must call pg_insert for PlayerInfo
        ON CONFLICT DO UPDATE."""
        session = _make_session()
        raw = _make_raw()
        pos_ids: tuple[int | None, int | None, int | None] = (1, None, None)

        with _pg_insert_mock(_REPO_MODULE) as mock_pg_insert:
            repo = PlayerInfoRepository(session)
            await repo.upsert_player_info(raw=raw, pos_ids=pos_ids)

        from infrastructure.persistence.models.shared.player_info import PlayerInfo

        call_tables = [c.args[0] for c in mock_pg_insert.call_args_list]
        assert PlayerInfo in call_tables

    async def test_upsert_player_info_updates_existing_row(self) -> None:
        """upsert_player_info must use on_conflict_do_update to handle existing rows."""
        session = _make_session()
        raw = _make_raw()
        pos_ids: tuple[int | None, int | None, int | None] = (2, 3, None)

        with _pg_insert_mock(_REPO_MODULE) as mock_pg_insert:
            stmt_mock = mock_pg_insert.return_value
            repo = PlayerInfoRepository(session)
            await repo.upsert_player_info(raw=raw, pos_ids=pos_ids)

        stmt_mock.on_conflict_do_update.assert_called_once()


class TestUpsertPosition:
    async def test_upsert_position_creates_new_position_and_returns_id(self) -> None:
        """upsert_position must insert and return the resulting position_id."""
        session = _make_session()

        # First execute call: INSERT ON CONFLICT DO NOTHING
        # Second execute call: SELECT position_id
        result_insert = MagicMock()
        result_select = MagicMock()
        result_select.scalar_one_or_none.return_value = 42
        session.execute.side_effect = [result_insert, result_select]

        with _pg_insert_mock(_REPO_MODULE):
            repo = PlayerInfoRepository(session)
            pos_id = await repo.upsert_position("FW")

        assert pos_id == 42

    async def test_upsert_position_returns_existing_id_on_conflict(self) -> None:
        """upsert_position must return the existing id even when INSERT is a no-op."""
        session = _make_session()

        result_insert = MagicMock()
        result_select = MagicMock()
        result_select.scalar_one_or_none.return_value = 7
        session.execute.side_effect = [result_insert, result_select]

        with _pg_insert_mock(_REPO_MODULE):
            repo = PlayerInfoRepository(session)
            pos_id = await repo.upsert_position("FW")

        assert pos_id == 7


class TestUpsertPhoto:
    async def test_upsert_photo_skips_insert_when_url_is_none(self) -> None:
        """upsert_photo must not touch the DB when photo_url is None."""
        session = _make_session()

        repo = PlayerInfoRepository(session)
        await repo.upsert_photo(player_id=_PLAYER_ID, photo_url=None)

        session.execute.assert_not_called()

    async def test_upsert_photo_inserts_row_when_url_present(self) -> None:
        """upsert_photo must call pg_insert for PlayerPhoto when a URL is given."""
        session = _make_session()

        with _pg_insert_mock(_REPO_MODULE) as mock_pg_insert:
            repo = PlayerInfoRepository(session)
            await repo.upsert_photo(
                player_id=_PLAYER_ID,
                photo_url="https://cdn.fbref.com/images/d70ce98e.jpg",
            )

        from infrastructure.persistence.models.shared.player_photo import PlayerPhoto

        call_tables = [c.args[0] for c in mock_pg_insert.call_args_list]
        assert PlayerPhoto in call_tables
