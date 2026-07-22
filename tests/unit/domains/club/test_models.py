"""Unit tests for CountrySquad and CountrySquadsPage domain models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from domains.club.models import CountrySquad, CountrySquadsPage

# ---------------------------------------------------------------------------
# CountrySquad — valid construction
# ---------------------------------------------------------------------------


def test_country_squad_valid_full() -> None:
    s = CountrySquad(
        fk_country="ARG",
        fk_flag="ar",
        confederation="CONMEBOL",
        clubs_url="https://fbref.com/en/country/clubs/ARG/Argentina-Football-Clubs",
        nat_team_men_url="https://fbref.com/en/squads/abcd1234/history/Argentina-Men-Stats-and-History",  # noqa: E501
        nat_team_women_url="https://fbref.com/en/squads/efgh5678/history/Argentina-Women-Stats-and-History",  # noqa: E501
        fbref_men_squad_id="abcd1234",
        fbref_women_squad_id="efgh5678",
    )
    assert s.fk_country == "ARG"
    assert s.fk_flag == "ar"
    assert s.confederation == "CONMEBOL"
    assert s.clubs_url == "https://fbref.com/en/country/clubs/ARG/Argentina-Football-Clubs"  # noqa: E501
    assert s.fbref_men_squad_id == "abcd1234"
    assert s.fbref_women_squad_id == "efgh5678"


def test_country_squad_nullable_fields_accept_none() -> None:
    s = CountrySquad(
        fk_country="AFG",
        clubs_url="https://fbref.com/en/country/clubs/AFG/Afghanistan-Football-Clubs",
    )
    assert s.fk_flag is None
    assert s.confederation is None
    assert s.nat_team_men_url is None
    assert s.nat_team_women_url is None
    assert s.fbref_men_squad_id is None
    assert s.fbref_women_squad_id is None


def test_country_squad_men_only() -> None:
    s = CountrySquad(
        fk_country="FRA",
        clubs_url="https://fbref.com/en/country/clubs/FRA/France-Football-Clubs",
        nat_team_men_url="https://fbref.com/en/squads/aaaabbbb/history/France-Men-Stats-and-History",  # noqa: E501
        fbref_men_squad_id="aaaabbbb",
    )
    assert s.nat_team_men_url is not None
    assert s.nat_team_women_url is None
    assert s.fbref_women_squad_id is None


# ---------------------------------------------------------------------------
# CountrySquad — fk_country bounds
# ---------------------------------------------------------------------------


def test_country_squad_fk_country_min_len() -> None:
    s = CountrySquad(
        fk_country="FR",
        clubs_url="https://fbref.com/en/country/clubs/FR/France-Football-Clubs",
    )
    assert s.fk_country == "FR"


def test_country_squad_fk_country_max_len() -> None:
    s = CountrySquad(
        fk_country="ABCDEFGHIJ",  # 10 chars
        clubs_url="https://fbref.com/en/country/clubs/ABCDEFGHIJ/Country-Football-Clubs",  # noqa: E501
    )
    assert len(s.fk_country) == 10


def test_country_squad_fk_country_too_short_raises() -> None:
    with pytest.raises(ValidationError):
        CountrySquad(
            fk_country="X",
            clubs_url="https://fbref.com/en/country/clubs/X/X-Football-Clubs",
        )


def test_country_squad_fk_country_too_long_raises() -> None:
    with pytest.raises(ValidationError):
        CountrySquad(
            fk_country="ABCDEFGHIJK",  # 11 chars
            clubs_url="https://fbref.com/en/country/clubs/ABCDEFGHIJK/Country-Football-Clubs",  # noqa: E501
        )


# ---------------------------------------------------------------------------
# CountrySquad — confederation uppercasing
# ---------------------------------------------------------------------------


def test_confederation_uppercased_from_lowercase() -> None:
    s = CountrySquad(
        fk_country="ENG",
        clubs_url="https://fbref.com/en/country/clubs/ENG/England-Football-Clubs",
        confederation="uefa",
    )
    assert s.confederation == "UEFA"


def test_confederation_mixed_case_uppercased() -> None:
    s = CountrySquad(
        fk_country="BRA",
        clubs_url="https://fbref.com/en/country/clubs/BRA/Brazil-Football-Clubs",
        confederation="Conmebol",
    )
    assert s.confederation == "CONMEBOL"


def test_confederation_none_preserved() -> None:
    s = CountrySquad(
        fk_country="AFG",
        clubs_url="https://fbref.com/en/country/clubs/AFG/Afghanistan-Football-Clubs",
        confederation=None,
    )
    assert s.confederation is None


# ---------------------------------------------------------------------------
# CountrySquad — fbref squad id max 8 chars
# ---------------------------------------------------------------------------


def test_fbref_men_squad_id_max_8_chars() -> None:
    s = CountrySquad(
        fk_country="ARG",
        clubs_url="https://fbref.com/en/country/clubs/ARG/Argentina-Football-Clubs",
        fbref_men_squad_id="abcd1234",
    )
    assert s.fbref_men_squad_id == "abcd1234"


def test_fbref_men_squad_id_too_long_raises() -> None:
    with pytest.raises(ValidationError):
        CountrySquad(
            fk_country="ARG",
            clubs_url="https://fbref.com/en/country/clubs/ARG/Argentina-Football-Clubs",
            fbref_men_squad_id="abcd12345",  # 9 chars
        )


def test_fbref_women_squad_id_too_long_raises() -> None:
    with pytest.raises(ValidationError):
        CountrySquad(
            fk_country="ARG",
            clubs_url="https://fbref.com/en/country/clubs/ARG/Argentina-Football-Clubs",
            fbref_women_squad_id="abcd12345",  # 9 chars
        )


def test_fbref_flag_id_max_2_chars() -> None:
    s = CountrySquad(
        fk_country="ARG",
        clubs_url="https://fbref.com/en/country/clubs/ARG/Argentina-Football-Clubs",
        fk_flag="ar",
    )
    assert s.fk_flag == "ar"


def test_fbref_flag_id_too_long_raises() -> None:
    with pytest.raises(ValidationError):
        CountrySquad(
            fk_country="ARG",
            clubs_url="https://fbref.com/en/country/clubs/ARG/Argentina-Football-Clubs",
            fk_flag="arg",  # 3 chars — too long
        )


# ---------------------------------------------------------------------------
# CountrySquadsPage
# ---------------------------------------------------------------------------


def test_country_squads_page_empty() -> None:
    page = CountrySquadsPage(squads=[])
    assert page.squads == []


def test_country_squads_page_with_rows() -> None:
    rows = [
        CountrySquad(
            fk_country="ARG",
            clubs_url="https://fbref.com/en/country/clubs/ARG/Argentina-Football-Clubs",
            confederation="CONMEBOL",
        ),
        CountrySquad(
            fk_country="ENG",
            clubs_url="https://fbref.com/en/country/clubs/ENG/England-Football-Clubs",
            confederation="UEFA",
        ),
    ]
    page = CountrySquadsPage(squads=rows)
    assert len(page.squads) == 2
    assert page.squads[0].fk_country == "ARG"
    assert page.squads[1].confederation == "UEFA"
