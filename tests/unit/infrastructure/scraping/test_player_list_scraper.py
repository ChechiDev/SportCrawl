"""Unit tests for PlayerListScraper (infrastructure/scraping/players.py).

All DB and network calls are mocked. asyncio_mode = "auto" via pyproject.toml
so no explicit @pytest.mark.asyncio decorators are needed.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from config.settings import ScrapingSettings
from core.exceptions.scraper import ScraperError
from domains.player.models import PlayerListPage
from infrastructure.scraping.players import PlayerListScraper
from ports.browser import ScrapingEngine

# ---------------------------------------------------------------------------
# HTML fixtures — FBRef-style player list using <p> tags
#
# FBRef country player-list pages use <p> tags, NOT tables with data-stat.
# Each player row is a <p> element containing:
#   - an <a href="/en/players/{8-char-id}/{Name}"> anchor
#   - <strong> wrapper inside the anchor for active players
#   - tail text: "{start}-{end}\xa0· {POS,POS}" (e.g. "2004-2026\xa0· FW,MF")
# ---------------------------------------------------------------------------

_PLAYER_LIST_HTML = """
<html><body>
<div class="section_content">
<p><a href="/en/players/d70ce98e/Lionel-Messi"><strong>Lionel Messi</strong></a> 2004-2026&nbsp;\xb7 FW,MF</p>
<p><a href="/en/players/abc12345/Roberto-Carlos">Roberto Carlos</a> 1991-2011&nbsp;\xb7 DF</p>
</div>
</body></html>
"""

_EMPTY_TABLE_HTML = """
<html><body>
<div class="section_content">
</div>
</body></html>
"""

_COUNTRY_ID = "ESP"
_BASE_URL = "https://fbref.com/en/country/players/ESP/Spain-Football"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _settings(**overrides: Any) -> ScrapingSettings:
    base: dict[str, Any] = {
        "max_retries": 1,
        "base_delay": 0.0,
        "max_delay": 0.0,
        "request_timeout": 30,
        "request_delay_min": 0.0,
        "request_delay_max": 0.0,
    }
    base.update(overrides)
    return ScrapingSettings(**base)


class MockEngine(ScrapingEngine):
    """Minimal in-memory engine that always returns a fixed HTML string."""

    def __init__(self, html: str = "") -> None:
        self._html = html

    async def fetch(self, _url: str) -> str:
        return self._html

    async def close(self) -> None:
        pass


def _make_scraper(
    html: str = _PLAYER_LIST_HTML,
    **setting_overrides: Any,
) -> PlayerListScraper:
    engine = MockEngine(html)
    session_factory = MagicMock()
    settings = _settings(**setting_overrides)
    return PlayerListScraper(engine, settings, session_factory)


# ---------------------------------------------------------------------------
# parse() tests — Task 5.1
# ---------------------------------------------------------------------------


class TestPlayerListScraperParse:
    """Tests for PlayerListScraper.parse() in isolation (no DB, no HTTP calls)."""

    async def test_parse_extracts_player_id_from_href(self) -> None:
        """parse() must extract the 8-char player_id via href regex."""
        scraper = _make_scraper()
        page = await scraper.parse(_PLAYER_LIST_HTML, country_id=_COUNTRY_ID)
        ids = [p.player_id for p in page.players]
        assert "d70ce98e" in ids

    async def test_parse_extracts_positions_in_order(self) -> None:
        """parse() must return positions in the order they appear (FW before MF)."""
        scraper = _make_scraper()
        page = await scraper.parse(_PLAYER_LIST_HTML, country_id=_COUNTRY_ID)
        messi = next(p for p in page.players if p.player_id == "d70ce98e")
        assert messi.positions == ["FW", "MF"]

    async def test_parse_active_player_career_end_is_none(self) -> None:
        """parse() must set career_end=None for active players (empty career_end)."""
        scraper = _make_scraper()
        page = await scraper.parse(_PLAYER_LIST_HTML, country_id=_COUNTRY_ID)
        messi = next(p for p in page.players if p.player_id == "d70ce98e")
        assert messi.career_end is None

    async def test_parse_retired_player_career_end_is_int(self) -> None:
        """parse() must set career_end to an int for retired players."""
        scraper = _make_scraper()
        page = await scraper.parse(_PLAYER_LIST_HTML, country_id=_COUNTRY_ID)
        carlos = next(p for p in page.players if p.player_id == "abc12345")
        assert carlos.career_end == 2011

    async def test_parse_extracts_career_start(self) -> None:
        """parse() must extract career_start as int from data-stat='career_start'."""
        scraper = _make_scraper()
        page = await scraper.parse(_PLAYER_LIST_HTML, country_id=_COUNTRY_ID)
        messi = next(p for p in page.players if p.player_id == "d70ce98e")
        assert messi.career_start == 2004

    async def test_parse_extracts_display_name_from_anchor_text(self) -> None:
        """parse() must use the anchor text as display_name."""
        scraper = _make_scraper()
        page = await scraper.parse(_PLAYER_LIST_HTML, country_id=_COUNTRY_ID)
        messi = next(p for p in page.players if p.player_id == "d70ce98e")
        assert messi.display_name == "Lionel Messi"

    async def test_parse_returns_player_list_page(self) -> None:
        """parse() must return a PlayerListPage instance."""
        scraper = _make_scraper()
        page = await scraper.parse(_PLAYER_LIST_HTML, country_id=_COUNTRY_ID)
        assert isinstance(page, PlayerListPage)

    async def test_parse_sets_country_id_on_page(self) -> None:
        """parse() must set the country_id from the scraper's _country_id attribute."""
        scraper = _make_scraper()
        page = await scraper.parse(_PLAYER_LIST_HTML, country_id=_COUNTRY_ID)
        assert page.country_id == _COUNTRY_ID

    async def test_parse_extracts_two_players(self) -> None:
        """parse() must return all valid player rows (2 in the fixture)."""
        scraper = _make_scraper()
        page = await scraper.parse(_PLAYER_LIST_HTML, country_id=_COUNTRY_ID)
        assert len(page.players) == 2

    async def test_parse_single_position_is_list(self) -> None:
        """parse() must wrap a single position code in a list."""
        scraper = _make_scraper()
        page = await scraper.parse(_PLAYER_LIST_HTML, country_id=_COUNTRY_ID)
        carlos = next(p for p in page.players if p.player_id == "abc12345")
        assert carlos.positions == ["DF"]

    async def test_parse_player_url_is_absolute(self) -> None:
        """parse() must produce an absolute URL for player_url."""
        scraper = _make_scraper()
        page = await scraper.parse(_PLAYER_LIST_HTML, country_id=_COUNTRY_ID)
        messi = next(p for p in page.players if p.player_id == "d70ce98e")
        assert messi.player_url.startswith("https://")

    async def test_parse_empty_table_returns_empty_list(self) -> None:
        """parse() with empty tbody must return a page with zero players."""
        scraper = _make_scraper()
        page = await scraper.parse(_EMPTY_TABLE_HTML, country_id=_COUNTRY_ID)
        assert page.players == []


# ---------------------------------------------------------------------------
# fetch_and_parse() tests — Task 5.2
# ---------------------------------------------------------------------------


class TestFetchAndParse:
    """Tests for PlayerListScraper.fetch_and_parse() override."""

    async def test_fetch_and_parse_calls_asyncio_sleep(self) -> None:
        """fetch_and_parse() must call asyncio.sleep with a value in [3.0, 10.0]."""
        # Use delay range 3.0–10.0 and pin the engine to return valid HTML
        engine = MockEngine(_PLAYER_LIST_HTML)
        session_factory = MagicMock()
        settings = _settings(
            request_delay_min=3.0,
            request_delay_max=10.0,
        )
        scraper = PlayerListScraper(engine, settings, session_factory)

        with patch("infrastructure.scraping.players.asyncio.sleep") as mock_sleep:
            mock_sleep.return_value = None  # avoid actual sleep
            await scraper.fetch_and_parse(_BASE_URL)

        mock_sleep.assert_called()
        sleep_arg = mock_sleep.call_args[0][0]
        assert 3.0 <= sleep_arg <= 10.0, (
            f"asyncio.sleep called with {sleep_arg!r}, expected value in [3.0, 10.0]"
        )

    async def test_fetch_and_parse_http_error_propagates(self) -> None:
        """fetch_and_parse() must propagate HTTP errors without returning a page."""
        from core.exceptions.scraper import PageLoadError

        class FailingEngine(ScrapingEngine):
            async def fetch(self, url: str) -> str:
                raise PageLoadError("server error", url=url)

            async def close(self) -> None:
                pass

        scraper = PlayerListScraper(
            FailingEngine(),
            _settings(max_retries=1),
            MagicMock(),
        )

        with pytest.raises(ScraperError):
            await scraper.fetch_and_parse(_BASE_URL)
