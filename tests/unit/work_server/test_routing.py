"""Unit tests for make_scraper_factory URL routing.

Verifies that PlayerListScraper and CountryScraper are registered in the
correct order — player pattern before country pattern to prevent collisions.
asyncio_mode = "auto" via pyproject.toml.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from core.exceptions.scraper import ScraperError
from infrastructure.scraping.countries import CountryScraper
from infrastructure.scraping.players import PlayerListScraper
from infrastructure.work_server.runtime import make_scraper_factory

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_test_factory() -> tuple[Any, Any, Any]:
    """Build a scraper factory via the real make_scraper_factory function."""
    browser_engine = MagicMock()
    scraping = MagicMock()
    scraping.max_retries = 1
    scraping.base_delay = 0.0
    scraping.max_delay = 0.0
    scraping.request_delay_min = 0.0
    scraping.request_delay_max = 0.0
    scraping.request_timeout = 30
    session_factory = MagicMock()

    factory = make_scraper_factory(browser_engine, scraping, session_factory)
    return factory, browser_engine, session_factory


# ---------------------------------------------------------------------------
# Routing tests — Task 6.3
# ---------------------------------------------------------------------------


class TestScraperFactoryRouting:
    """Tests for make_scraper_factory URL routing."""

    def test_player_list_url_routes_to_player_list_scraper(self) -> None:
        """Player list URL must resolve to PlayerListScraper, not CountryScraper."""
        factory, _, _ = _make_test_factory()
        url = "https://fbref.com/en/country/players/ESP/Spain-Football"
        scraper = factory(url)
        assert isinstance(scraper, PlayerListScraper), (
            f"Expected PlayerListScraper, got {type(scraper).__name__}"
        )

    def test_country_url_routes_to_country_scraper(self) -> None:
        """Country listing URL must still resolve to CountryScraper (no collision)."""
        factory, _, _ = _make_test_factory()
        url = "https://fbref.com/en/countries/"
        scraper = factory(url)
        assert isinstance(scraper, CountryScraper), (
            f"Expected CountryScraper, got {type(scraper).__name__}"
        )

    def test_player_url_does_not_resolve_to_country_scraper(self) -> None:
        """Player list URL must NOT be routed to CountryScraper."""
        factory, _, _ = _make_test_factory()
        url = "https://fbref.com/en/country/players/ESP/Spain-Football"
        scraper = factory(url)
        assert not isinstance(scraper, CountryScraper)

    def test_unknown_url_raises_scraper_error(self) -> None:
        """Unregistered URL must raise ScraperError."""
        factory, _, _ = _make_test_factory()
        with pytest.raises(ScraperError):
            factory("https://example.com/unknown")

    def test_player_list_scraper_uses_injected_engine(self) -> None:
        """PlayerListScraper must be built with the shared browser engine."""
        factory, browser_engine, _ = _make_test_factory()
        url = "https://fbref.com/en/country/players/ARG/Argentina-Football"
        scraper = factory(url)
        assert isinstance(scraper, PlayerListScraper)
        assert scraper._engine is browser_engine

    def test_two_player_url_calls_return_different_instances(self) -> None:
        """Each factory call must return a new PlayerListScraper instance."""
        factory, _, _ = _make_test_factory()
        url = "https://fbref.com/en/country/players/ESP/Spain-Football"
        s1 = factory(url)
        s2 = factory(url)
        assert s1 is not s2
