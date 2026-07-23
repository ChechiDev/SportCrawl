"""Unit tests for Team and TeamsPage domain models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from domains.club.models import Team, TeamsPage

# ---------------------------------------------------------------------------
# Team — valid construction
# ---------------------------------------------------------------------------


def test_team_valid_full() -> None:
    t = Team(
        team_id="abcd1234",
        team_name="Arsenal",
        fk_country="ENG",
        gender_raw="M",
        comp_name="Premier League",
        team_from=2000,
        team_to=2024,
        team_url="https://fbref.com/en/squads/abcd1234/Arsenal-Stats",
    )
    assert t.team_id == "abcd1234"
    assert t.team_name == "Arsenal"
    assert t.fk_country == "ENG"
    assert t.gender_raw == "M"
    assert t.comp_name == "Premier League"
    assert t.team_from == 2000
    assert t.team_to == 2024
    assert t.team_url == "https://fbref.com/en/squads/abcd1234/Arsenal-Stats"


def test_team_nullable_fields_accept_none() -> None:
    t = Team(
        team_id="abcd1234",
        team_name="Arsenal",
        fk_country="ENG",
        gender_raw="M",
        team_url="https://fbref.com/en/squads/abcd1234/Arsenal-Stats",
    )
    assert t.comp_name is None
    assert t.team_from is None
    assert t.team_to is None


def test_team_gender_female() -> None:
    t = Team(
        team_id="ef012678",
        team_name="Arsenal Women",
        fk_country="ENG",
        gender_raw="F",
        team_url="https://fbref.com/en/squads/ef012678/Arsenal-Women-Stats",
    )
    assert t.gender_raw == "F"


# ---------------------------------------------------------------------------
# Team — team_id validation (exactly 8 chars)
# ---------------------------------------------------------------------------


def test_team_id_exactly_8_chars() -> None:
    t = Team(
        team_id="abcd1234",
        team_name="Club",
        fk_country="ARG",
        gender_raw="M",
        team_url="https://fbref.com/en/squads/abcd1234/Club-Stats",
    )
    assert len(t.team_id) == 8


def test_team_id_too_short_raises() -> None:
    with pytest.raises(ValidationError):
        Team(
            team_id="abc123",  # 6 chars
            team_name="Club",
            fk_country="ARG",
            gender_raw="M",
            team_url="https://fbref.com/en/squads/abc123/Club-Stats",
        )


def test_team_id_too_long_raises() -> None:
    with pytest.raises(ValidationError):
        Team(
            team_id="abcd12345",  # 9 chars
            team_name="Club",
            fk_country="ARG",
            gender_raw="M",
            team_url="https://fbref.com/en/squads/abcd12345/Club-Stats",
        )


# ---------------------------------------------------------------------------
# Team — team_name bounds
# ---------------------------------------------------------------------------


def test_team_name_empty_raises() -> None:
    with pytest.raises(ValidationError):
        Team(
            team_id="abcd1234",
            team_name="",
            fk_country="ARG",
            gender_raw="M",
            team_url="https://fbref.com/en/squads/abcd1234/Club-Stats",
        )


def test_team_name_max_200_chars() -> None:
    name = "A" * 200
    t = Team(
        team_id="abcd1234",
        team_name=name,
        fk_country="ARG",
        gender_raw="M",
        team_url="https://fbref.com/en/squads/abcd1234/Club-Stats",
    )
    assert len(t.team_name) == 200


def test_team_name_too_long_raises() -> None:
    with pytest.raises(ValidationError):
        Team(
            team_id="abcd1234",
            team_name="A" * 201,
            fk_country="ARG",
            gender_raw="M",
            team_url="https://fbref.com/en/squads/abcd1234/Club-Stats",
        )


# ---------------------------------------------------------------------------
# Team — team_url bounds
# ---------------------------------------------------------------------------


def test_team_url_empty_raises() -> None:
    with pytest.raises(ValidationError):
        Team(
            team_id="abcd1234",
            team_name="Club",
            fk_country="ARG",
            gender_raw="M",
            team_url="",
        )


# ---------------------------------------------------------------------------
# TeamsPage
# ---------------------------------------------------------------------------


def test_teams_page_empty() -> None:
    page = TeamsPage(fk_country="ARG")
    assert page.fk_country == "ARG"
    assert page.teams == []


def test_teams_page_with_rows() -> None:
    teams = [
        Team(
            team_id="abcd1234",
            team_name="River Plate",
            fk_country="ARG",
            gender_raw="M",
            team_url="https://fbref.com/en/squads/abcd1234/River-Plate-Stats",
        ),
        Team(
            team_id="ef012678",
            team_name="Boca Juniors",
            fk_country="ARG",
            gender_raw="M",
            team_url="https://fbref.com/en/squads/ef012678/Boca-Juniors-Stats",
        ),
    ]
    page = TeamsPage(fk_country="ARG", teams=teams)
    assert len(page.teams) == 2
    assert page.teams[0].team_id == "abcd1234"
    assert page.teams[1].team_name == "Boca Juniors"
