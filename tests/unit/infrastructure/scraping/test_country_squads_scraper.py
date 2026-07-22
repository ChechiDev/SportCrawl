"""Unit tests for CountrySquadsScraper.parse() (infrastructure/scraping/country_squads.py).

All DB and network calls are mocked. asyncio_mode = "auto" via pyproject.toml
so no explicit @pytest.mark.asyncio decorators are needed.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from config.settings import ScrapingSettings
from core.exceptions.scraper import ParsingError
from domains.club.models import CountrySquadsPage
from infrastructure.scraping.country_squads import CountrySquadsScraper
from ports.browser import ScrapingEngine

# ---------------------------------------------------------------------------
# HTML fixtures (inline — no file dependency needed for unit tests)
# ---------------------------------------------------------------------------

_FULL_ROW_HTML = """
<html><body>
<table id="countries">
  <thead><tr><th>Country</th></tr></thead>
  <tbody>
    <tr>
      <th scope="row" data-stat="country"><strong>Albania Football Clubs</strong></th>
      <td data-stat="flag"><span class="f-i f-al"></span></td>
      <td data-stat="governing_body">UEFA</td>
      <td data-stat="club_count">
        <a href="/en/country/clubs/ALB/Albania-Football-Clubs">42</a>
      </td>
      <td data-stat="national_teams">
        <a href="/en/squads/abcd1234/history/Albania-Mens-Stats">Men</a>
        <a href="/en/squads/efgh5678/history/Albania-Womens-Stats">Women</a>
      </td>
    </tr>
  </tbody>
</table>
</body></html>
"""

_MEN_ONLY_HTML = """
<html><body>
<table id="countries">
  <tbody>
    <tr>
      <th scope="row" data-stat="country"><strong>Andorra Football Clubs</strong></th>
      <td data-stat="flag"><span class="f-i f-ad"></span></td>
      <td data-stat="governing_body">UEFA</td>
      <td data-stat="club_count">
        <a href="/en/country/clubs/AND/Andorra-Football-Clubs">5</a>
      </td>
      <td data-stat="national_teams">
        <a href="/en/squads/aaaa1111/history/Andorra-Mens-Stats">Men</a>
      </td>
    </tr>
  </tbody>
</table>
</body></html>
"""

_NO_NATIONAL_TEAMS_HTML = """
<html><body>
<table id="countries">
  <tbody>
    <tr>
      <th scope="row" data-stat="country"><strong>Fictonia Football Clubs</strong></th>
      <td data-stat="flag"><span class="f-i f-fx"></span></td>
      <td data-stat="governing_body">CONMEBOL</td>
      <td data-stat="club_count">
        <a href="/en/country/clubs/FIC/Fictonia-Football-Clubs">10</a>
      </td>
      <td data-stat="national_teams"></td>
    </tr>
  </tbody>
</table>
</body></html>
"""

_MULTI_ROW_HTML = """
<html><body>
<table id="countries">
  <tbody>
    <tr>
      <th scope="row" data-stat="country"><strong>Albania Football Clubs</strong></th>
      <td data-stat="flag"><span class="f-i f-al"></span></td>
      <td data-stat="governing_body">UEFA</td>
      <td data-stat="club_count">
        <a href="/en/country/clubs/ALB/Albania-Football-Clubs">42</a>
      </td>
      <td data-stat="national_teams">
        <a href="/en/squads/abcd1234/history/Albania-Mens-Stats">Men</a>
        <a href="/en/squads/efgh5678/history/Albania-Womens-Stats">Women</a>
      </td>
    </tr>
    <tr>
      <th scope="row" data-stat="country"><strong>Andorra Football Clubs</strong></th>
      <td data-stat="flag"><span class="f-i f-ad"></span></td>
      <td data-stat="governing_body">UEFA</td>
      <td data-stat="club_count">
        <a href="/en/country/clubs/AND/Andorra-Football-Clubs">5</a>
      </td>
      <td data-stat="national_teams">
        <a href="/en/squads/aaaa1111/history/Andorra-Mens-Stats">Men</a>
      </td>
    </tr>
  </tbody>
</table>
</body></html>
"""

_NO_TABLE_HTML = """
<html><body>
<p>No squads table here.</p>
</body></html>
"""

_EMPTY_TBODY_HTML = """
<html><body>
<table id="countries">
  <tbody></tbody>
</table>
</body></html>
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FBREF_BASE = "https://fbref.com"


def _settings(**overrides: Any) -> ScrapingSettings:
    base: dict[str, Any] = {
        "max_retries": 3,
        "base_delay": 1.0,
        "max_delay": 60.0,
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

    async def fetch(self, url: str) -> str:  # noqa: ARG002
        return self._html

    async def close(self) -> None:
        pass


def _make_scraper(html: str = "") -> CountrySquadsScraper:
    engine = MockEngine(html)
    session_factory = MagicMock()
    return CountrySquadsScraper(engine, _settings(), session_factory)


# ---------------------------------------------------------------------------
# Parse tests
# ---------------------------------------------------------------------------


class TestCountrySquadsScraperParse:
    """Tests for CountrySquadsScraper.parse() in isolation (no DB calls)."""

    # --- return type ---

    async def test_parse_returns_country_squads_page(self) -> None:
        scraper = _make_scraper()
        page = await scraper.parse(_FULL_ROW_HTML)
        assert isinstance(page, CountrySquadsPage)

    async def test_parse_returns_correct_number_of_rows(self) -> None:
        scraper = _make_scraper()
        page = await scraper.parse(_MULTI_ROW_HTML)
        assert len(page.squads) == 2

    async def test_parse_empty_table_returns_empty_page(self) -> None:
        scraper = _make_scraper()
        page = await scraper.parse(_EMPTY_TBODY_HTML)
        assert page.squads == []

    async def test_parse_missing_table_raises_parsing_error(self) -> None:
        scraper = _make_scraper()
        with pytest.raises(ParsingError):
            await scraper.parse(_NO_TABLE_HTML)

    # --- country code extraction ---

    async def test_parse_extracts_country_code_from_clubs_url(self) -> None:
        scraper = _make_scraper()
        page = await scraper.parse(_FULL_ROW_HTML)
        assert page.squads[0].fk_country == "ALB"

    async def test_parse_country_code_is_uppercase(self) -> None:
        scraper = _make_scraper()
        page = await scraper.parse(_FULL_ROW_HTML)
        assert page.squads[0].fk_country.isupper()

    # --- clubs_url ---

    async def test_parse_extracts_clubs_url_as_full_url(self) -> None:
        scraper = _make_scraper()
        page = await scraper.parse(_FULL_ROW_HTML)
        assert page.squads[0].clubs_url == (
            f"{_FBREF_BASE}/en/country/clubs/ALB/Albania-Football-Clubs"
        )

    # --- flag extraction ---

    async def test_parse_extracts_flag_2letter_code(self) -> None:
        scraper = _make_scraper()
        page = await scraper.parse(_FULL_ROW_HTML)
        assert page.squads[0].fk_flag == "al"

    # --- confederation ---

    async def test_parse_extracts_confederation_name(self) -> None:
        scraper = _make_scraper()
        page = await scraper.parse(_FULL_ROW_HTML)
        assert page.squads[0].confederation == "UEFA"

    async def test_parse_confederation_is_uppercased(self) -> None:
        html = _FULL_ROW_HTML.replace(">UEFA<", ">uefa<")
        scraper = _make_scraper()
        page = await scraper.parse(html)
        assert page.squads[0].confederation == "UEFA"

    # --- men's national team ---

    async def test_parse_extracts_men_nat_team_url(self) -> None:
        scraper = _make_scraper()
        page = await scraper.parse(_FULL_ROW_HTML)
        assert page.squads[0].nat_team_men_url == (
            f"{_FBREF_BASE}/en/squads/abcd1234/history/Albania-Mens-Stats"
        )

    async def test_parse_extracts_men_squad_id(self) -> None:
        scraper = _make_scraper()
        page = await scraper.parse(_FULL_ROW_HTML)
        assert page.squads[0].fbref_men_squad_id == "abcd1234"

    # --- women's national team ---

    async def test_parse_extracts_women_nat_team_url(self) -> None:
        scraper = _make_scraper()
        page = await scraper.parse(_FULL_ROW_HTML)
        assert page.squads[0].nat_team_women_url == (
            f"{_FBREF_BASE}/en/squads/efgh5678/history/Albania-Womens-Stats"
        )

    async def test_parse_extracts_women_squad_id(self) -> None:
        scraper = _make_scraper()
        page = await scraper.parse(_FULL_ROW_HTML)
        assert page.squads[0].fbref_women_squad_id == "efgh5678"

    # --- men-only row (no women's team) ---

    async def test_parse_men_only_row_women_url_is_none(self) -> None:
        scraper = _make_scraper()
        page = await scraper.parse(_MEN_ONLY_HTML)
        assert page.squads[0].nat_team_women_url is None

    async def test_parse_men_only_row_women_squad_id_is_none(self) -> None:
        scraper = _make_scraper()
        page = await scraper.parse(_MEN_ONLY_HTML)
        assert page.squads[0].fbref_women_squad_id is None

    async def test_parse_men_only_row_men_url_is_set(self) -> None:
        scraper = _make_scraper()
        page = await scraper.parse(_MEN_ONLY_HTML)
        assert page.squads[0].nat_team_men_url is not None
        assert page.squads[0].fbref_men_squad_id == "aaaa1111"

    # --- row with no national teams ---

    async def test_parse_no_national_teams_both_urls_none(self) -> None:
        scraper = _make_scraper()
        page = await scraper.parse(_NO_NATIONAL_TEAMS_HTML)
        squad = page.squads[0]
        assert squad.nat_team_men_url is None
        assert squad.nat_team_women_url is None
        assert squad.fbref_men_squad_id is None
        assert squad.fbref_women_squad_id is None

    async def test_parse_no_national_teams_still_returns_row(self) -> None:
        scraper = _make_scraper()
        page = await scraper.parse(_NO_NATIONAL_TEAMS_HTML)
        assert len(page.squads) == 1
        assert page.squads[0].fk_country == "FIC"

    # --- multi-row correctness ---

    async def test_parse_multi_row_second_entry_correct(self) -> None:
        scraper = _make_scraper()
        page = await scraper.parse(_MULTI_ROW_HTML)
        second = page.squads[1]
        assert second.fk_country == "AND"
        assert second.fk_flag == "ad"
        assert second.fbref_men_squad_id == "aaaa1111"
        assert second.fbref_women_squad_id is None
