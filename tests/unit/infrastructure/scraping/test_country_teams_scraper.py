"""Unit tests for CountryTeamsScraper.parse() (infrastructure/scraping/country_teams).

All DB and network calls are mocked. asyncio_mode = "auto" via pyproject.toml
so no explicit @pytest.mark.asyncio decorators are needed.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from config.settings import ScrapingSettings
from core.exceptions.scraper import ParsingError
from domains.club.models import TeamsPage
from infrastructure.scraping.country_teams import CountryTeamsScraper
from ports.browser import ScrapingEngine


# ---------------------------------------------------------------------------
# HTML fixtures
# ---------------------------------------------------------------------------

_FULL_ROW_HTML = """
<html><body>
<table id="clubs">
  <thead><tr><th>Team</th></tr></thead>
  <tbody>
    <tr>
      <th data-stat="team">
        <a href="/en/squads/abcd1234/Arsenal-Stats">Arsenal</a>
      </th>
      <td data-stat="gender">M</td>
      <td data-stat="comp">Premier League</td>
      <td data-stat="min_season">2000-2001</td>
      <td data-stat="max_season">2023-2024</td>
    </tr>
  </tbody>
</table>
</body></html>
"""

_WOMEN_ROW_HTML = """
<html><body>
<table id="clubs">
  <tbody>
    <tr>
      <th data-stat="team">
        <a href="/en/squads/ef012678/Arsenal-Women-Stats">Arsenal Women</a>
      </th>
      <td data-stat="gender">F</td>
      <td data-stat="comp">WSL</td>
      <td data-stat="min_season">2011-2012</td>
      <td data-stat="max_season">2023-2024</td>
    </tr>
  </tbody>
</table>
</body></html>
"""

_NO_COMP_HTML = """
<html><body>
<table id="clubs">
  <tbody>
    <tr>
      <th data-stat="team">
        <a href="/en/squads/aaaa1111/Some-Club-Stats">Some Club</a>
      </th>
      <td data-stat="gender">M</td>
      <td data-stat="comp"></td>
      <td data-stat="min_season">2010-2011</td>
      <td data-stat="max_season">2020-2021</td>
    </tr>
  </tbody>
</table>
</body></html>
"""

_HEADER_ROW_HTML = """
<html><body>
<table id="clubs">
  <tbody>
    <tr class="thead">
      <th data-stat="team">Team</th>
    </tr>
    <tr>
      <th data-stat="team">
        <a href="/en/squads/bbbb2222/Real-Club-Stats">Real Club</a>
      </th>
      <td data-stat="gender">M</td>
      <td data-stat="comp">La Liga</td>
      <td data-stat="min_season">2000-2001</td>
      <td data-stat="max_season">2023-2024</td>
    </tr>
  </tbody>
</table>
</body></html>
"""

_INVALID_GENDER_HTML = """
<html><body>
<table id="clubs">
  <tbody>
    <tr>
      <th data-stat="team">
        <a href="/en/squads/cccc3333/Club-Stats">Club</a>
      </th>
      <td data-stat="gender">X</td>
      <td data-stat="comp">League</td>
      <td data-stat="min_season">2000-2001</td>
      <td data-stat="max_season">2020-2021</td>
    </tr>
  </tbody>
</table>
</body></html>
"""

_NO_TABLE_HTML = """
<html><body><p>No clubs table here.</p></body></html>
"""

_MISSING_HREF_HTML = """
<html><body>
<table id="clubs">
  <tbody>
    <tr>
      <th data-stat="team"><span>No link here</span></th>
      <td data-stat="gender">M</td>
    </tr>
  </tbody>
</table>
</body></html>
"""

_INVALID_SEASON_HTML = """
<html><body>
<table id="clubs">
  <tbody>
    <tr>
      <th data-stat="team">
        <a href="/en/squads/dddd4444/Club-Stats">Club</a>
      </th>
      <td data-stat="gender">M</td>
      <td data-stat="comp">League</td>
      <td data-stat="min_season">2020</td>
      <td data-stat="max_season">2021</td>
    </tr>
  </tbody>
</table>
</body></html>
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_scraper(fk_country: str = "ENG") -> CountryTeamsScraper:
    engine: Any = MagicMock(spec=ScrapingEngine)
    settings: Any = MagicMock(spec=ScrapingSettings)
    session_factory: Any = MagicMock()
    return CountryTeamsScraper(engine, settings, session_factory, fk_country=fk_country)


# ---------------------------------------------------------------------------
# parse() — happy path
# ---------------------------------------------------------------------------


async def test_parse_full_row() -> None:
    scraper = _make_scraper("ENG")
    page = await scraper.parse(_FULL_ROW_HTML)
    assert isinstance(page, TeamsPage)
    assert page.fk_country == "ENG"
    assert len(page.teams) == 1
    team = page.teams[0]
    assert team.team_id == "abcd1234"
    assert team.team_name == "Arsenal"
    assert team.fk_country == "ENG"
    assert team.gender_raw == "M"
    assert team.comp_name == "Premier League"
    assert team.team_from == 2000
    assert team.team_to == 2024
    assert team.team_url == "https://fbref.com/en/squads/abcd1234/Arsenal-Stats"


async def test_parse_women_row() -> None:
    scraper = _make_scraper("ENG")
    page = await scraper.parse(_WOMEN_ROW_HTML)
    assert len(page.teams) == 1
    assert page.teams[0].gender_raw == "F"
    assert page.teams[0].team_from == 2011
    assert page.teams[0].team_to == 2024


async def test_parse_no_comp_returns_none() -> None:
    scraper = _make_scraper("ARG")
    page = await scraper.parse(_NO_COMP_HTML)
    assert len(page.teams) == 1
    assert page.teams[0].comp_name is None


async def test_parse_skips_header_rows() -> None:
    scraper = _make_scraper("ESP")
    page = await scraper.parse(_HEADER_ROW_HTML)
    assert len(page.teams) == 1
    assert page.teams[0].team_id == "bbbb2222"


async def test_parse_skips_invalid_gender() -> None:
    scraper = _make_scraper("ARG")
    page = await scraper.parse(_INVALID_GENDER_HTML)
    assert page.teams == []


async def test_parse_skips_missing_href() -> None:
    scraper = _make_scraper("ARG")
    page = await scraper.parse(_MISSING_HREF_HTML)
    assert page.teams == []


async def test_parse_invalid_season_format_returns_none_years() -> None:
    scraper = _make_scraper("ARG")
    page = await scraper.parse(_INVALID_SEASON_HTML)
    assert len(page.teams) == 1
    assert page.teams[0].team_from is None
    assert page.teams[0].team_to is None


# ---------------------------------------------------------------------------
# parse() — no table raises ParsingError
# ---------------------------------------------------------------------------


async def test_parse_no_clubs_table_raises() -> None:
    scraper = _make_scraper("ENG")
    with pytest.raises(ParsingError, match="clubs table not found"):
        await scraper.parse(_NO_TABLE_HTML)


# ---------------------------------------------------------------------------
# parse() — empty tbody yields empty page
# ---------------------------------------------------------------------------


async def test_parse_empty_tbody() -> None:
    html = """
    <html><body>
    <table id="clubs"><tbody></tbody></table>
    </body></html>
    """
    scraper = _make_scraper("ENG")
    page = await scraper.parse(html)
    assert page.teams == []
