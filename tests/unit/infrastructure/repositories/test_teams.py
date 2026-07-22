"""Unit tests for TeamsRepository.

All database calls are mocked via AsyncMock session + patched pg_insert.
asyncio_mode = "auto" via pyproject.toml — no explicit @pytest.mark.asyncio.
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.exceptions.repository import RepositoryError
from domains.club.models import Team
from infrastructure.persistence.repositories.teams import TeamsRepository

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REPO_MODULE = "infrastructure.persistence.repositories.teams"


def _make_session() -> AsyncMock:
    session = AsyncMock()
    result = MagicMock()
    result.__iter__ = MagicMock(return_value=iter([]))
    session.execute.return_value = result
    return session


@contextmanager
def _pg_insert_mock():
    with patch(f"{_REPO_MODULE}.pg_insert") as mock_pg_insert:
        stmt_mock = MagicMock()
        stmt_mock.values.return_value = stmt_mock
        stmt_mock.on_conflict_do_nothing.return_value = stmt_mock
        stmt_mock.on_conflict_do_update.return_value = stmt_mock
        stmt_mock.excluded = MagicMock()
        mock_pg_insert.return_value = stmt_mock
        yield mock_pg_insert


def _make_team(
    team_id: str = "abcd1234",
    team_name: str = "Arsenal",
    fk_country: str = "ENG",
    gender_raw: str = "M",
    comp_name: str | None = "Premier League",
    team_from: int | None = 2000,
    team_to: int | None = 2024,
    team_url: str = "https://fbref.com/en/squads/abcd1234/Arsenal-Stats",
) -> Team:
    return Team(
        team_id=team_id,
        team_name=team_name,
        fk_country=fk_country,
        gender_raw=gender_raw,
        comp_name=comp_name,
        team_from=team_from,
        team_to=team_to,
        team_url=team_url,
    )


# ---------------------------------------------------------------------------
# upsert() — empty list is a no-op
# ---------------------------------------------------------------------------


async def test_upsert_empty_list_is_noop() -> None:
    session = _make_session()
    repo = TeamsRepository(session)
    with _pg_insert_mock():
        await repo.upsert([])
    session.execute.assert_not_called()


# ---------------------------------------------------------------------------
# upsert() — happy path: executes comp + gender + teams statements
# ---------------------------------------------------------------------------


async def test_upsert_executes_statements() -> None:
    session = _make_session()

    # Mock execute to return gender rows on the second call (gender lookup)
    comp_result = MagicMock()
    comp_result.__iter__ = MagicMock(return_value=iter([]))

    gender_row = MagicMock()
    gender_row.gender = "M"
    gender_row.id = 1
    gender_result = MagicMock()
    gender_result.__iter__ = MagicMock(return_value=iter([gender_row]))

    comp_fetch_row = MagicMock()
    comp_fetch_row.comp_name = "Premier League"
    comp_fetch_row.comp_id = 42
    comp_fetch_result = MagicMock()
    comp_fetch_result.__iter__ = MagicMock(return_value=iter([comp_fetch_row]))

    # Call sequence: (1) comp insert, (2) comp fetch, (3) gender fetch, (4) teams insert
    session.execute.side_effect = [
        comp_result,       # comp insert (on_conflict_do_nothing)
        comp_fetch_result, # comp select
        gender_result,     # gender select
        MagicMock(),       # teams insert
    ]

    repo = TeamsRepository(session)
    with _pg_insert_mock():
        await repo.upsert([_make_team()])

    assert session.execute.call_count == 4


async def test_upsert_no_comp_skips_comp_insert() -> None:
    """When comp_name is None for all rows, comp insert is skipped."""
    session = _make_session()

    gender_row = MagicMock()
    gender_row.gender = "M"
    gender_row.id = 1
    gender_result = MagicMock()
    gender_result.__iter__ = MagicMock(return_value=iter([gender_row]))

    # Only 2 calls: gender fetch + teams insert
    session.execute.side_effect = [
        gender_result,  # gender select
        MagicMock(),    # teams insert
    ]

    repo = TeamsRepository(session)
    with _pg_insert_mock():
        await repo.upsert([_make_team(comp_name=None)])

    assert session.execute.call_count == 2


# ---------------------------------------------------------------------------
# upsert() — SQLAlchemy error raises RepositoryError
# ---------------------------------------------------------------------------


async def test_upsert_sqlalchemy_error_raises_repository_error() -> None:
    from sqlalchemy.exc import SQLAlchemyError

    session = _make_session()
    session.execute.side_effect = SQLAlchemyError("DB down")

    repo = TeamsRepository(session)
    with _pg_insert_mock():
        with pytest.raises(RepositoryError):
            await repo.upsert([_make_team()])
