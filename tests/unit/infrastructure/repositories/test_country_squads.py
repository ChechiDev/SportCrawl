"""Unit tests for CountrySquadsRepository.

All database calls are mocked via AsyncMock session + patched pg_insert.
asyncio_mode = "auto" via pyproject.toml — no explicit @pytest.mark.asyncio.
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from domains.club.models import CountrySquad
from infrastructure.persistence.repositories.country_squads import (
    CountrySquadsRepository,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REPO_MODULE = "infrastructure.persistence.repositories.country_squads"


def _make_session() -> AsyncMock:
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one.return_value = None
    result.scalar_one_or_none.return_value = None
    session.execute.return_value = result
    return session


@contextmanager
def _pg_insert_mock():
    with patch(f"{_REPO_MODULE}.pg_insert") as mock_pg_insert:
        stmt_mock = MagicMock()
        stmt_mock.values.return_value = stmt_mock
        stmt_mock.on_conflict_do_nothing.return_value = stmt_mock
        stmt_mock.on_conflict_do_update.return_value = stmt_mock
        stmt_mock.returning.return_value = stmt_mock
        mock_pg_insert.return_value = stmt_mock
        yield mock_pg_insert


def _make_squad(
    fk_country: str = "ARG",
    confederation: str | None = "CONMEBOL",
    fk_flag: str | None = "ar",
    clubs_url: str = "https://fbref.com/en/country/clubs/ARG/Argentina-Football-Clubs",
    nat_team_men_url: str
    | None = "https://fbref.com/en/squads/abcd1234/history/Argentina-Men",  # noqa: E501
    nat_team_women_url: str | None = None,
    fbref_men_squad_id: str | None = "abcd1234",
    fbref_women_squad_id: str | None = None,
) -> CountrySquad:
    return CountrySquad(
        fk_country=fk_country,
        confederation=confederation,
        fk_flag=fk_flag,
        clubs_url=clubs_url,
        nat_team_men_url=nat_team_men_url,
        nat_team_women_url=nat_team_women_url,
        fbref_men_squad_id=fbref_men_squad_id,
        fbref_women_squad_id=fbref_women_squad_id,
    )


# ---------------------------------------------------------------------------
# Tests — confederation upsert
# ---------------------------------------------------------------------------


class TestConfederationUpsert:
    async def test_confederation_upserted_with_on_conflict_do_nothing(self) -> None:
        """upsert must insert confederation with ON CONFLICT DO NOTHING."""
        session = _make_session()
        squad = _make_squad(confederation="CONMEBOL")

        with _pg_insert_mock() as mock_pg_insert:
            stmt_mock = mock_pg_insert.return_value
            repo = CountrySquadsRepository(session)
            await repo.upsert([squad])

        stmt_mock.on_conflict_do_nothing.assert_called()

    async def test_confederation_not_inserted_when_none(self) -> None:
        """When confederation is None, pg_insert must NOT be called for it."""
        session = _make_session()
        squad = _make_squad(confederation=None)

        with _pg_insert_mock() as mock_pg_insert:
            from infrastructure.persistence.models.shared.confederation import (
                Confederation,
            )

            repo = CountrySquadsRepository(session)
            await repo.upsert([squad])

        confederation_calls = [
            c
            for c in mock_pg_insert.call_args_list
            if c.args and c.args[0] is Confederation
        ]
        assert len(confederation_calls) == 0

    async def test_existing_confederation_does_not_duplicate(self) -> None:
        """ON CONFLICT DO NOTHING: no duplicate row, session.execute is still called."""
        session = _make_session()
        squad = _make_squad(confederation="UEFA")

        with _pg_insert_mock():
            repo = CountrySquadsRepository(session)
            await repo.upsert([squad])

        # execute was called (for confederation + squad rows)
        assert session.execute.call_count >= 2


# ---------------------------------------------------------------------------
# Tests — squad upsert
# ---------------------------------------------------------------------------


class TestSquadUpsert:
    async def test_upsert_calls_pg_insert_for_country_squads(self) -> None:
        """upsert must call pg_insert(CountrySquads)."""
        session = _make_session()
        squad = _make_squad()

        with _pg_insert_mock() as mock_pg_insert:
            from infrastructure.persistence.models.shared.country_squads import (
                CountrySquads,
            )

            repo = CountrySquadsRepository(session)
            await repo.upsert([squad])

        squad_calls = [
            c
            for c in mock_pg_insert.call_args_list
            if c.args and c.args[0] is CountrySquads
        ]
        assert len(squad_calls) == 1

    async def test_upsert_uses_on_conflict_do_update(self) -> None:
        """ON CONFLICT (fk_country) DO UPDATE must be used for squad rows."""
        session = _make_session()
        squad = _make_squad()

        with _pg_insert_mock() as mock_pg_insert:
            stmt_mock = mock_pg_insert.return_value
            repo = CountrySquadsRepository(session)
            await repo.upsert([squad])

        stmt_mock.on_conflict_do_update.assert_called()

    async def test_upsert_batches_rows(self) -> None:
        """upsert with N squads calls execute exactly 2 times (conf + squad batch)."""
        session = _make_session()
        squads = [
            _make_squad("ARG"),
            _make_squad(
                "ENG",
                confederation="UEFA",
                fk_flag="gb",
                clubs_url="https://fbref.com/en/country/clubs/ENG/England-Football-Clubs",  # noqa: E501
                nat_team_men_url=None,
                fbref_men_squad_id=None,
            ),
        ]

        with _pg_insert_mock():
            repo = CountrySquadsRepository(session)
            await repo.upsert(squads)

        # batch upsert: 1 confederation batch + 1 squad batch = 2 execute calls total
        assert session.execute.call_count == 2

    async def test_upsert_empty_list_does_not_execute(self) -> None:
        """Passing an empty list must not call execute at all."""
        session = _make_session()

        with _pg_insert_mock():
            repo = CountrySquadsRepository(session)
            await repo.upsert([])

        session.execute.assert_not_called()


# ---------------------------------------------------------------------------
# Tests — error handling
# ---------------------------------------------------------------------------


class TestUpsertErrorHandling:
    async def test_sqlalchemy_error_raises_repository_error(self) -> None:
        """SQLAlchemyError must be caught and re-raised as RepositoryError."""
        from sqlalchemy.exc import SQLAlchemyError

        from core.exceptions.repository import RepositoryError

        session = _make_session()
        session.execute.side_effect = SQLAlchemyError("db error")
        squad = _make_squad()

        with _pg_insert_mock():
            repo = CountrySquadsRepository(session)
            with pytest.raises(RepositoryError):
                await repo.upsert([squad])
