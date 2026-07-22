"""End-to-end smoke test for CountrySquadsScraper.

Exercises the full parse → persist → repository upsert path with mocked HTTP
fetch and mocked database session. No live network or DB required.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from config.settings import ScrapingSettings
from domains.club.models import CountrySquad, CountrySquadsPage
from infrastructure.scraping.country_squads import CountrySquadsScraper
from ports.browser import ScrapingEngine

# ---------------------------------------------------------------------------
# Shared fixture HTML (two full rows — Albania + Andorra)
# ---------------------------------------------------------------------------

_E2E_HTML = """
<html><body>
<table id="squads">
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

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
    """Returns a fixed HTML string for any URL."""

    def __init__(self, html: str) -> None:
        self._html = html

    async def fetch(self, url: str) -> str:  # noqa: ARG002
        return self._html

    async def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# E2E smoke test
# ---------------------------------------------------------------------------


class TestCountrySquadsE2E:
    """End-to-end: mocked HTTP + mocked DB → parse + persist pipeline."""

    async def test_scrape_calls_upsert_with_parsed_squads(self) -> None:
        """scrape() must parse HTML and call repo.upsert with all valid rows."""
        mock_session = AsyncMock()
        mock_session.commit = AsyncMock()

        mock_repo = AsyncMock()
        mock_repo.upsert = AsyncMock()

        @asynccontextmanager
        async def _fake_get_session(
            _factory: Any,
        ) -> AsyncGenerator[AsyncMock, None]:  # type: ignore[misc]
            yield mock_session

        engine = MockEngine(_E2E_HTML)
        session_factory = MagicMock()
        scraper = CountrySquadsScraper(engine, _settings(), session_factory)

        with (
            patch(
                "infrastructure.scraping.country_squads.get_session",
                side_effect=_fake_get_session,
            ),
            patch(
                "infrastructure.scraping.country_squads.CountrySquadsRepository",
                return_value=mock_repo,
            ),
        ):
            page = await scraper.scrape("https://fbref.com/en/squads/")

        # Parse result assertions.
        assert isinstance(page, CountrySquadsPage)
        assert len(page.squads) == 2
        assert all(isinstance(s, CountrySquad) for s in page.squads)

        # Albania row.
        alb = page.squads[0]
        assert alb.fk_country == "ALB"
        assert alb.fk_flag == "al"
        assert alb.confederation == "UEFA"
        assert alb.fbref_men_squad_id == "abcd1234"
        assert alb.fbref_women_squad_id == "efgh5678"

        # Andorra row (men-only).
        and_ = page.squads[1]
        assert and_.fk_country == "AND"
        assert and_.fbref_men_squad_id == "aaaa1111"
        assert and_.fbref_women_squad_id is None

        # Persistence assertions.
        mock_repo.upsert.assert_called_once_with(page.squads)
        mock_session.commit.assert_called_once()
