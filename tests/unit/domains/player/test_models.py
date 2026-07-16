"""Unit tests for PlayerRawData and PlayerListPage domain models."""

import pytest
from pydantic import ValidationError

from domains.player.models import PlayerListPage, PlayerRawData

_PLAYER_URL = "https://fbref.com/en/players/d70ce98e/Lionel-Messi"
_PLAYER_URL_2 = "https://fbref.com/en/players/abc12345/Some-Player"


# ---------------------------------------------------------------------------
# PlayerRawData — valid construction
# ---------------------------------------------------------------------------


def test_player_raw_data_valid_active_player() -> None:
    p = PlayerRawData(
        player_id="d70ce98e",
        full_name="Lionel Messi",
        career_start=2004,
        career_end=2004,  # active: equals career_start
        player_url=_PLAYER_URL,
    )
    assert p.player_id == "d70ce98e"
    assert p.full_name == "Lionel Messi"
    assert p.career_start == 2004
    assert p.career_end == 2004
    assert p.player_url == _PLAYER_URL


def test_player_raw_data_retired_player_career_end_is_int() -> None:
    """career_end must be an int for retired players."""
    p = PlayerRawData(
        player_id="abc12345",
        full_name="Retired Player",
        career_start=1990,
        career_end=2010,
        player_url=_PLAYER_URL_2,
    )
    assert p.career_end == 2010
    assert isinstance(p.career_end, int)


# ---------------------------------------------------------------------------
# PlayerRawData — validation errors
# ---------------------------------------------------------------------------


def test_player_raw_data_missing_player_id_raises() -> None:
    with pytest.raises(ValidationError):
        PlayerRawData(  # type: ignore[call-arg]
            full_name="Test",
            career_start=2000,
            career_end=2000,
            player_url=_PLAYER_URL,
        )


def test_player_raw_data_missing_full_name_raises() -> None:
    with pytest.raises(ValidationError):
        PlayerRawData(  # type: ignore[call-arg]
            player_id="abc12345",
            career_start=2000,
            career_end=2000,
            player_url=_PLAYER_URL,
        )


def test_player_raw_data_missing_career_start_raises() -> None:
    with pytest.raises(ValidationError):
        PlayerRawData(  # type: ignore[call-arg]
            player_id="abc12345",
            full_name="Test",
            career_end=2000,
            player_url=_PLAYER_URL,
        )


# ---------------------------------------------------------------------------
# PlayerListPage
# ---------------------------------------------------------------------------


def test_player_list_page_with_players() -> None:
    players = [
        PlayerRawData(
            player_id="d70ce98e",
            full_name="Lionel Messi",
            career_start=2004,
            career_end=2004,
            player_url=_PLAYER_URL,
        ),
        PlayerRawData(
            player_id="abc12345",
            full_name="Another Player",
            career_start=1990,
            career_end=2005,
            player_url=_PLAYER_URL_2,
        ),
    ]
    page = PlayerListPage(country_id="ARG", players=players)
    assert page.country_id == "ARG"
    assert len(page.players) == 2
    assert page.players[0].player_id == "d70ce98e"
    assert page.players[1].career_end == 2005


def test_player_list_page_empty_players() -> None:
    page = PlayerListPage(country_id="ESP", players=[])
    assert page.country_id == "ESP"
    assert page.players == []
