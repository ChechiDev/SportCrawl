"""Unit tests for PlayerInfoRawData and PlayerInfoPage domain models.

RED phase: these tests are written before the implementation exists.
They MUST fail initially (ImportError or assertion failures).
"""

from __future__ import annotations

from datetime import date

from domains.player_info.models import PlayerInfoPage, PlayerInfoRawData

# ---------------------------------------------------------------------------
# PlayerInfoRawData — construction
# ---------------------------------------------------------------------------


def test_player_info_raw_data_all_none() -> None:
    """PlayerInfoRawData must allow all optional fields to be None."""
    raw = PlayerInfoRawData(
        player_id="abc123",
        player_info_url="https://fbref.com/en/players/abc123/Test-Player",
    )
    assert raw.player_id == "abc123"
    assert raw.fk_country_birth is None
    assert raw.city_name is None
    assert raw.player_born is None
    assert raw.player_height is None
    assert raw.player_weight is None
    assert raw.position_1 is None
    assert raw.position_2 is None
    assert raw.position_3 is None
    assert raw.player_foot is None
    assert raw.player_wages is None
    assert raw.player_expires is None
    assert raw.photo_url is None


def test_player_info_raw_data_all_fields() -> None:
    """PlayerInfoRawData must accept all optional fields when provided."""
    raw = PlayerInfoRawData(
        player_id="abc123",
        fk_country_birth="ARG",
        city_name="Buenos Aires",
        player_born=date(1987, 6, 24),
        player_height=170,
        player_weight=67,
        position_1="FW",
        position_2="MF",
        position_3=None,
        player_foot="Left",
        player_wages=500000,
        player_expires=date(2025, 6, 30),
        player_info_url="https://fbref.com/en/players/abc123/Test-Player",
        photo_url="https://cdn.fbref.com/photos/abc123.jpg",
    )
    assert raw.player_id == "abc123"
    assert raw.fk_country_birth == "ARG"
    assert raw.city_name == "Buenos Aires"
    assert raw.player_born == date(1987, 6, 24)
    assert raw.player_height == 170
    assert raw.player_weight == 67
    assert raw.position_1 == "FW"
    assert raw.position_2 == "MF"
    assert raw.position_3 is None
    assert raw.player_foot == "Left"
    assert raw.player_wages == 500000
    assert raw.player_expires == date(2025, 6, 30)
    assert raw.photo_url == "https://cdn.fbref.com/photos/abc123.jpg"


def test_player_info_raw_data_wages_zero_is_valid() -> None:
    """player_wages=0 must be stored as 0, not treated as missing/None."""
    raw = PlayerInfoRawData(
        player_id="abc123",
        player_wages=0,
        player_info_url="https://fbref.com/en/players/abc123/Test-Player",
    )
    assert raw.player_wages == 0
    assert raw.player_wages is not None


def test_player_info_raw_data_no_player_age_field() -> None:
    """PlayerInfoRawData MUST NOT have a player_age attribute."""
    raw = PlayerInfoRawData(
        player_id="abc123",
        player_info_url="https://fbref.com/en/players/abc123/Test-Player",
    )
    assert not hasattr(raw, "player_age")


# ---------------------------------------------------------------------------
# PlayerInfoPage — construction
# ---------------------------------------------------------------------------


def test_player_info_page_empty_list() -> None:
    """PlayerInfoPage must accept an empty list of players."""
    page = PlayerInfoPage(players=[])
    assert page.players == []


def test_player_info_page_wraps_list_of_raw_data() -> None:
    """PlayerInfoPage.players must be a list of PlayerInfoRawData."""
    raw = PlayerInfoRawData(
        player_id="abc123",
        player_info_url="https://fbref.com/en/players/abc123/Test-Player",
    )
    page = PlayerInfoPage(players=[raw])
    assert len(page.players) == 1
    assert page.players[0].player_id == "abc123"


def test_player_info_page_multiple_players() -> None:
    """PlayerInfoPage must accept multiple PlayerInfoRawData entries."""
    raw1 = PlayerInfoRawData(
        player_id="aaa111",
        player_info_url="https://fbref.com/en/players/aaa111/Player-One",
    )
    raw2 = PlayerInfoRawData(
        player_id="bbb222",
        player_wages=0,
        player_info_url="https://fbref.com/en/players/bbb222/Player-Two",
    )
    page = PlayerInfoPage(players=[raw1, raw2])
    assert len(page.players) == 2
    assert page.players[1].player_wages == 0


def test_player_info_page_no_player_age_field() -> None:
    """PlayerInfoPage MUST NOT have a player_age attribute."""
    page = PlayerInfoPage(players=[])
    assert not hasattr(page, "player_age")
