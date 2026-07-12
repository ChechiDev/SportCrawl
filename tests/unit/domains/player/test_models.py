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
        display_name="Lionel Messi",
        full_name="Lionel Andrés Messi Cuccittini",
        career_start=2004,
        career_end=None,
        positions=["FW", "MF"],
        player_url=_PLAYER_URL,
    )
    assert p.player_id == "d70ce98e"
    assert p.display_name == "Lionel Messi"
    assert p.full_name == "Lionel Andrés Messi Cuccittini"
    assert p.career_start == 2004
    assert p.career_end is None
    assert p.positions == ["FW", "MF"]
    assert p.player_url == _PLAYER_URL


def test_player_raw_data_active_player_career_end_is_none() -> None:
    """career_end must be None for active players — no inference allowed."""
    p = PlayerRawData(
        player_id="abc12345",
        display_name="Active Player",
        full_name=None,
        career_start=2015,
        career_end=None,
        positions=["GK"],
        player_url=_PLAYER_URL_2,
    )
    assert p.career_end is None


def test_player_raw_data_retired_player_career_end_is_int() -> None:
    """career_end must be an int for retired players."""
    p = PlayerRawData(
        player_id="abc12345",
        display_name="Retired Player",
        full_name=None,
        career_start=1990,
        career_end=2010,
        positions=["DF"],
        player_url=_PLAYER_URL_2,
    )
    assert p.career_end == 2010
    assert isinstance(p.career_end, int)


def test_player_raw_data_positions_ordered_by_appearance() -> None:
    """positions must be a list preserving scrape order — not a set."""
    p = PlayerRawData(
        player_id="abc12345",
        display_name="Multi-pos Player",
        full_name=None,
        career_start=2000,
        career_end=None,
        positions=["GK", "DF", "MF"],
        player_url=_PLAYER_URL_2,
    )
    # Order must be preserved exactly as provided
    assert p.positions == ["GK", "DF", "MF"]
    assert p.positions[0] == "GK"
    assert p.positions[1] == "DF"
    assert p.positions[2] == "MF"


def test_player_raw_data_positions_single_entry() -> None:
    """positions works with a single position."""
    p = PlayerRawData(
        player_id="abc12345",
        display_name="Single Pos",
        full_name=None,
        career_start=2010,
        career_end=None,
        positions=["FW"],
        player_url=_PLAYER_URL_2,
    )
    assert p.positions == ["FW"]


def test_player_raw_data_full_name_optional() -> None:
    """full_name may be None."""
    p = PlayerRawData(
        player_id="abc12345",
        display_name="No Full Name",
        full_name=None,
        career_start=2005,
        career_end=None,
        positions=["MF"],
        player_url=_PLAYER_URL_2,
    )
    assert p.full_name is None


# ---------------------------------------------------------------------------
# PlayerRawData — validation errors
# ---------------------------------------------------------------------------


def test_player_raw_data_missing_player_id_raises() -> None:
    with pytest.raises(ValidationError):
        PlayerRawData(  # type: ignore[call-arg]
            display_name="Test",
            full_name=None,
            career_start=2000,
            career_end=None,
            positions=["FW"],
            player_url=_PLAYER_URL,
        )


def test_player_raw_data_missing_display_name_raises() -> None:
    with pytest.raises(ValidationError):
        PlayerRawData(  # type: ignore[call-arg]
            player_id="abc12345",
            full_name=None,
            career_start=2000,
            career_end=None,
            positions=["FW"],
            player_url=_PLAYER_URL,
        )


def test_player_raw_data_missing_career_start_raises() -> None:
    with pytest.raises(ValidationError):
        PlayerRawData(  # type: ignore[call-arg]
            player_id="abc12345",
            display_name="Test",
            full_name=None,
            career_end=None,
            positions=["FW"],
            player_url=_PLAYER_URL,
        )


# ---------------------------------------------------------------------------
# PlayerListPage
# ---------------------------------------------------------------------------


def test_player_list_page_with_players() -> None:
    players = [
        PlayerRawData(
            player_id="d70ce98e",
            display_name="Lionel Messi",
            full_name=None,
            career_start=2004,
            career_end=None,
            positions=["FW"],
            player_url=_PLAYER_URL,
        ),
        PlayerRawData(
            player_id="abc12345",
            display_name="Another Player",
            full_name=None,
            career_start=1990,
            career_end=2005,
            positions=["DF"],
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
