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


class TestUpsertCity:
    async def test_upsert_city_inserts_new_city_and_returns_id(self) -> None:
        """upsert_city must execute INSERT and return the city_id from SELECT."""
        session = _make_session()

        result_insert = MagicMock()
        result_select = MagicMock()
        result_select.scalar.return_value = 99
        session.execute.side_effect = [result_insert, result_select]

        repo = PlayerInfoRepository(session)
        city_id = await repo.upsert_city("Buenos Aires")

        assert city_id == 99
        assert session.execute.call_count == 2
        # First call: INSERT
        first_sql = str(session.execute.call_args_list[0][0][0])
        assert "tbl_cities" in first_sql
        assert "ON CONFLICT" in first_sql
        first_params = session.execute.call_args_list[0][0][1]
        assert first_params["city_name"] == "Buenos Aires"

    async def test_upsert_city_returns_existing_id_on_conflict(self) -> None:
        """upsert_city must return the existing city_id even when INSERT is a no-op."""
        session = _make_session()

        result_insert = MagicMock()
        result_select = MagicMock()
        result_select.scalar.return_value = 7
        session.execute.side_effect = [result_insert, result_select]

        repo = PlayerInfoRepository(session)
        city_id = await repo.upsert_city("Rosario")

        assert city_id == 7

    async def test_upsert_player_info_uses_fk_city_not_city_name(self) -> None:
        """upsert_player_info must pass fk_city (int FK), not city_name (string)."""
        session = _make_session()
        raw = _make_raw()
        raw.fk_city = 42
        pos_ids: tuple[int | None, int | None, int | None] = (1, None, None)

        with _pg_insert_mock(_REPO_MODULE) as mock_pg_insert:
            stmt_mock = mock_pg_insert.return_value
            repo = PlayerInfoRepository(session)
            await repo.upsert_player_info(raw=raw, pos_ids=pos_ids)

        # The values dict passed to .values() must contain fk_city, not city_name
        values_call_kwargs = stmt_mock.values.call_args[1]
        assert "fk_city" in values_call_kwargs
        assert "city_name" not in values_call_kwargs
        assert values_call_kwargs["fk_city"] == 42

    async def test_upsert_player_info_uses_fk_nat_team_not_fk_national_team(
        self,
    ) -> None:
        """upsert_player_info must use fk_nat_team column, not fk_national_team."""
        session = _make_session()
        raw = _make_raw()
        raw.fk_nat_team = "ARG"
        pos_ids: tuple[int | None, int | None, int | None] = (1, None, None)

        with _pg_insert_mock(_REPO_MODULE) as mock_pg_insert:
            stmt_mock = mock_pg_insert.return_value
            repo = PlayerInfoRepository(session)
            await repo.upsert_player_info(raw=raw, pos_ids=pos_ids)

        values_call_kwargs = stmt_mock.values.call_args[1]
        assert "fk_nat_team" in values_call_kwargs
        assert "fk_national_team" not in values_call_kwargs
        assert values_call_kwargs["fk_nat_team"] == "ARG"

    async def test_upsert_player_info_includes_fk_team_and_player_age(
        self,
    ) -> None:
        """upsert_player_info includes fk_team/age; excludes club_name/club_url."""
        session = _make_session()
        raw = _make_raw()
        raw.fk_team = "0e08d4eb"
        raw.player_age = 38
        pos_ids: tuple[int | None, int | None, int | None] = (1, None, None)

        with _pg_insert_mock(_REPO_MODULE) as mock_pg_insert:
            stmt_mock = mock_pg_insert.return_value
            repo = PlayerInfoRepository(session)
            await repo.upsert_player_info(raw=raw, pos_ids=pos_ids)

        values_call_kwargs = stmt_mock.values.call_args[1]
        assert "fk_team" in values_call_kwargs
        assert values_call_kwargs["fk_team"] == "0e08d4eb"
        assert "player_age" in values_call_kwargs
        assert values_call_kwargs["player_age"] == 38
        assert "club_name" not in values_call_kwargs
        assert "club_url" not in values_call_kwargs


class TestUpsertCitizenship:
    async def test_upsert_citizenship_executes_insert(self) -> None:
        """upsert_citizenship must call session.execute with the correct SQL."""
        session = _make_session()

        repo = PlayerInfoRepository(session)
        await repo.upsert_citizenship(player_id=_PLAYER_ID, fk_country="ARG")

        session.execute.assert_called_once()
        call_args = session.execute.call_args
        # First positional arg is the sa.text statement
        sql_text = str(call_args[0][0])
        assert "tbl_player_citizenship" in sql_text
        assert "ON CONFLICT" in sql_text
        # Second arg is the bind params dict
        params = call_args[0][1]
        assert params["player_id"] == _PLAYER_ID
        assert params["fk_country"] == "ARG"

    async def test_upsert_citizenship_passes_correct_params(self) -> None:
        """upsert_citizenship must bind player_id and fk_country correctly."""
        session = _make_session()

        repo = PlayerInfoRepository(session)
        await repo.upsert_citizenship(player_id="xyz99999", fk_country="BRA")

        params = session.execute.call_args[0][1]
        assert params["player_id"] == "xyz99999"
        assert params["fk_country"] == "BRA"


class TestUpsertTeamStub:
    async def test_upsert_team_stub_executes_insert_on_conflict_do_nothing(
        self,
    ) -> None:
        """upsert_team_stub must INSERT into tbl_teams with ON CONFLICT DO NOTHING."""
        session = _make_session()

        repo = PlayerInfoRepository(session)
        await repo.upsert_team_stub(
            team_id="0e08d4eb",
            team_url="https://fbref.com/en/squads/0e08d4eb/Barcelona",
        )

        session.execute.assert_called_once()
        call_args = session.execute.call_args
        sql_text = str(call_args[0][0])
        assert "tbl_teams" in sql_text
        assert "ON CONFLICT" in sql_text
        params = call_args[0][1]
        assert params["team_id"] == "0e08d4eb"
        assert params["team_url"] == "https://fbref.com/en/squads/0e08d4eb/Barcelona"

    async def test_upsert_team_stub_passes_none_url_as_null(self) -> None:
        """upsert_team_stub passes None as team_url when absent, not empty string."""
        session = _make_session()

        repo = PlayerInfoRepository(session)
        await repo.upsert_team_stub(team_id="abc12345", team_url=None)

        params = session.execute.call_args[0][1]
        assert params["team_url"] is None

    async def test_upsert_team_stub_idempotent_on_second_call(self) -> None:
        """Calling upsert_team_stub twice for the same team_id must not raise."""
        session = _make_session()

        repo = PlayerInfoRepository(session)
        await repo.upsert_team_stub(team_id="0e08d4eb", team_url=None)
        await repo.upsert_team_stub(team_id="0e08d4eb", team_url=None)

        assert session.execute.call_count == 2
