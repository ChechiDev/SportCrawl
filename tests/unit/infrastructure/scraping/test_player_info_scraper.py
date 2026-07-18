"""Unit tests for PlayerInfoScraper (infrastructure/scraping/player_info.py).

All DB and network calls are mocked. asyncio_mode = "auto" via pyproject.toml.
Tests use a fixture HTML snapshot of a real FBRef player profile page.
"""

from __future__ import annotations

from pathlib import Path

from infrastructure.scraping.player_info import PlayerInfoScraper

# ---------------------------------------------------------------------------
# HTML fixture
# ---------------------------------------------------------------------------

_FIXTURE_PATH = Path(__file__).parents[3] / "fixtures" / "fbref_player_profile.html"
_PROFILE_HTML = _FIXTURE_PATH.read_text(encoding="utf-8")

_PLAYER_ID = "d70ce98e"
_PLAYER_URL = "https://fbref.com/en/players/d70ce98e/Lionel-Messi"

_MISSING_FIELDS_HTML = """
<html><body>
<div id="meta">
  <h1 itemprop="name"><span>Ghost Player</span></h1>
</div>
</body></html>
"""

_WAGES_ZERO_HTML = """
<html><body>
<div id="meta">
  <h1 itemprop="name"><span>Cheap Player</span></h1>
  <p><strong>Weekly Wages</strong>: £0</p>
</div>
</body></html>
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_scraper(
    player_id: str = _PLAYER_ID, player_url: str = _PLAYER_URL
) -> PlayerInfoScraper:
    return PlayerInfoScraper(player_id=player_id, player_info_url=player_url)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPlayerInfoScraperParse:
    """Tests for PlayerInfoScraper.parse() — synchronous (not async)."""

    def test_parse_returns_player_info_page(self) -> None:
        """parse() must return a PlayerInfoPage with one player entry (sync call)."""
        from domains.player_info.models import PlayerInfoPage

        scraper = _make_scraper()
        result = scraper.parse(_PROFILE_HTML)

        assert isinstance(result, PlayerInfoPage)
        assert len(result.players) == 1
        assert result.players[0].player_id == _PLAYER_ID

    def test_parse_extracts_position_codes(self) -> None:
        """'FW-MF' in HTML → position_1='FW', position_2='MF', position_3=None."""
        scraper = _make_scraper()
        result = scraper.parse(_PROFILE_HTML)

        player = result.players[0]
        assert player.position_1 == "FW"
        assert player.position_2 == "MF"
        assert player.position_3 is None

    def test_parse_extracts_birth_date(self) -> None:
        """parse() must extract the birth date from the HTML."""
        from datetime import date

        scraper = _make_scraper()
        result = scraper.parse(_PROFILE_HTML)

        assert result.players[0].player_born == date(1987, 6, 24)

    def test_parse_extracts_height_weight(self) -> None:
        """parse() must extract height (cm int) and weight (kg int)."""
        scraper = _make_scraper()
        result = scraper.parse(_PROFILE_HTML)

        player = result.players[0]
        assert player.player_height == 170
        assert player.player_weight == 72

    def test_parse_extracts_photo_url(self) -> None:
        """parse() must extract the photo img src URL."""
        scraper = _make_scraper()
        result = scraper.parse(_PROFILE_HTML)

        assert result.players[0].photo_url == (
            "https://cdn.fbref.com/req/202301011/images/players/d70ce98e.jpg"
        )

    def test_parse_missing_optional_fields_returns_none(self) -> None:
        """Fields absent from HTML must yield None, not raise an error."""
        scraper = PlayerInfoScraper(
            player_id="ghost00x", player_info_url="https://fbref.com/ghost"
        )
        result = scraper.parse(_MISSING_FIELDS_HTML)

        player = result.players[0]
        assert player.player_born is None
        assert player.player_height is None
        assert player.player_weight is None
        assert player.position_1 is None
        assert player.photo_url is None

    def test_parse_wages_zero_is_not_none(self) -> None:
        """player_wages=0 must be stored as 0, not converted to None."""
        scraper = PlayerInfoScraper(
            player_id="cheap00x", player_info_url="https://fbref.com/cheap"
        )
        result = scraper.parse(_WAGES_ZERO_HTML)

        assert result.players[0].player_wages == 0

    def test_parse_extracts_citizenship_name(self) -> None:
        """Extract citizenship name from Citizenship paragraph."""
        scraper = _make_scraper()
        result = scraper.parse(_PROFILE_HTML)

        assert result.players[0].citizenship_name == "Spain"

    def test_parse_extracts_youth_nat_team_name(self) -> None:
        """Extract youth national team name from paragraph."""
        scraper = _make_scraper()
        result = scraper.parse(_PROFILE_HTML)

        assert result.players[0].youth_nat_team_name == "Spain"

    def test_parse_extracts_club(self) -> None:
        """_parse_club() must return club_name and club_url from the Club paragraph."""
        scraper = _make_scraper()
        result = scraper.parse(_PROFILE_HTML)

        player = result.players[0]
        assert player.club_name == "Valle Egués"
        assert player.club_url == "/en/squads/0e08d4eb/Valle-Egues-Stats"
