"""Unit tests for CountryScraper (infrastructure/scraping/countries.py).

All DB and network calls are mocked. asyncio_mode = "auto" via pyproject.toml
so no explicit @pytest.mark.asyncio decorators are needed.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from config.settings import ScrapingSettings
from core.exceptions.scraper import ParsingError, ScraperError
from domains.country.models import CountryPage, CountryRawData
from infrastructure.scraping.countries import CountryScraper
from infrastructure.work_server.runtime import make_scraper_factory
from ports.browser import ScrapingEngine

# ---------------------------------------------------------------------------
# Fixtures: HTML
# ---------------------------------------------------------------------------

_ONE_ROW_HTML = """
<html><body>
<table id="countries">
  <thead><tr><th>Flag</th><th>Country</th><th>Conf</th></tr></thead>
  <tbody>
    <tr>
      <td data-stat="flag"><span>gb</span></td>
      <td data-stat="country">
        <a href="/en/country/ENG/England-Football">England</a>
      </td>
      <td data-stat="governing_body">UEFA</td>
    </tr>
  </tbody>
</table>
</body></html>
"""

_LOWERCASE_HREF_HTML = """
<html><body>
<table id="countries">
  <tbody>
    <tr>
      <td data-stat="flag"><span>es</span></td>
      <td data-stat="country">
        <a href="/en/country/esp/Spain-Football">Spain</a>
      </td>
      <td data-stat="governing_body">UEFA</td>
    </tr>
  </tbody>
</table>
</body></html>
"""

_EMPTY_TBODY_HTML = """
<html><body>
<table id="countries">
  <tbody></tbody>
</table>
</body></html>
"""

_NO_TABLE_HTML = """
<html><body>
<p>No countries table here.</p>
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
    """Minimal in-memory engine that always returns a fixed HTML string."""

    def __init__(self, html: str = "") -> None:
        self._html = html

    async def fetch(self, url: str) -> str:  # noqa: ARG002
        return self._html

    async def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Parse tests — tasks 4.2 / 4.4
# ---------------------------------------------------------------------------


class TestCountryScraperParse:
    """Tests for CountryScraper.parse() in isolation (no DB calls)."""

    async def _parse(self, html: str) -> CountryPage:
        """Run parse() — pure HTML parsing, no DB involved."""
        engine = MockEngine(html)
        session_factory = MagicMock()
        scraper = CountryScraper(engine, _settings(), session_factory)
        return await scraper.parse(html)

    # --- field extraction ---

    async def test_parse_extracts_country_id_from_href(self) -> None:
        page = await self._parse(_ONE_ROW_HTML)
        assert page.countries[0].country_id == "ENG"

    async def test_parse_extracts_country_name(self) -> None:
        page = await self._parse(_ONE_ROW_HTML)
        assert page.countries[0].country_name == "England"

    async def test_parse_extracts_confederation(self) -> None:
        page = await self._parse(_ONE_ROW_HTML)
        assert page.countries[0].confederation == "UEFA"

    async def test_parse_extracts_flag_id(self) -> None:
        page = await self._parse(_ONE_ROW_HTML)
        assert page.countries[0].flag_id == "gb"

    async def test_parse_builds_correct_flag_url(self) -> None:
        page = await self._parse(_ONE_ROW_HTML)
        assert page.countries[0].flag_url == (
            "https://cdn.fbref.com/req/202301010/images/flags/gb.gif"
        )

    # --- return type ---

    async def test_parse_returns_country_page(self) -> None:
        page = await self._parse(_ONE_ROW_HTML)
        assert isinstance(page, CountryPage)

    async def test_parse_returns_one_country_for_one_row(self) -> None:
        page = await self._parse(_ONE_ROW_HTML)
        assert len(page.countries) == 1
        assert isinstance(page.countries[0], CountryRawData)

    # --- edge cases ---

    async def test_parse_empty_table_returns_empty_page(self) -> None:
        page = await self._parse(_EMPTY_TBODY_HTML)
        assert isinstance(page, CountryPage)
        assert page.countries == []

    async def test_parse_missing_table_raises_parsing_error(self) -> None:
        with pytest.raises(ParsingError):
            await self._parse(_NO_TABLE_HTML)

    async def test_parse_lowercase_href_normalised_to_uppercase(self) -> None:
        """country_id derived from lowercase href segment must be uppercased."""
        page = await self._parse(_LOWERCASE_HREF_HTML)
        assert page.countries[0].country_id == "ESP"


# ---------------------------------------------------------------------------
# Persist tests — FIX 3 (SRP)
# ---------------------------------------------------------------------------


class TestCountryScraperPersist:
    """Tests for CountryScraper.persist() in isolation."""

    async def test_persist_calls_upsert(self) -> None:
        """persist() must call CountryRepository.upsert with the page's country list."""
        mock_session = AsyncMock()
        mock_session.commit = AsyncMock()

        mock_repo = AsyncMock()
        mock_repo.upsert = AsyncMock()

        @asynccontextmanager
        async def _fake_get_session(
            _factory: Any,
        ) -> AsyncGenerator[AsyncMock, None]:  # type: ignore[misc]
            yield mock_session

        engine = MockEngine(_ONE_ROW_HTML)
        session_factory = MagicMock()
        scraper = CountryScraper(engine, _settings(), session_factory)

        # Build a page directly (no DB involved in parse)
        page = await scraper.parse(_ONE_ROW_HTML)

        with (
            patch(
                "infrastructure.scraping.countries.get_session",
                side_effect=_fake_get_session,
            ),
            patch(
                "infrastructure.scraping.countries.CountryRepository",
                return_value=mock_repo,
            ),
        ):
            await scraper.persist(page)

        mock_repo.upsert.assert_called_once_with(page.countries)
        mock_session.commit.assert_called_once()


# ---------------------------------------------------------------------------
# Factory tests — tasks 5.1 / 5.3  (FIX 4: use make_scraper_factory directly)
# ---------------------------------------------------------------------------


def _make_test_factory() -> tuple[Any, Any, Any]:
    """Build a scraper factory via the real make_scraper_factory function."""
    browser_engine = MagicMock()
    scraping = _settings()
    session_factory = MagicMock()

    factory = make_scraper_factory(browser_engine, scraping, session_factory)
    return factory, browser_engine, session_factory


class TestScraperFactory:
    """Tests for the scraper_factory routing logic via make_scraper_factory."""

    def test_country_url_returns_country_scraper(self) -> None:
        factory, _, _ = _make_test_factory()
        scraper = factory("https://fbref.com/en/countries/")
        assert isinstance(scraper, CountryScraper)

    def test_unknown_url_raises_scraper_error(self) -> None:
        factory, _, _ = _make_test_factory()
        with pytest.raises(ScraperError):
            factory("https://fbref.com/en/players/")

    def test_two_country_url_calls_return_different_scraper_instances(self) -> None:
        """Each call produces a new CountryScraper wrapping the SAME engine."""
        factory, browser_engine, _ = _make_test_factory()
        s1 = factory("https://fbref.com/en/countries/")
        s2 = factory("https://fbref.com/en/countries/")
        assert s1 is not s2
        assert s1._engine is browser_engine  # type: ignore[attr-defined]
        assert s2._engine is browser_engine  # type: ignore[attr-defined]

    def test_partial_url_match_still_routes_to_country_scraper(self) -> None:
        """fbref.com/en/countries anywhere in the URL is sufficient."""
        factory, _, _ = _make_test_factory()
        scraper = factory("https://fbref.com/en/countries?page=2")
        assert isinstance(scraper, CountryScraper)
