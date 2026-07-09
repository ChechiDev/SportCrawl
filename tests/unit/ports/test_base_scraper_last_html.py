"""Tests for BaseScraper.last_html property.

Verifies that:
- fetch_and_parse populates last_html with the raw HTML string returned by engine.
- last_html is updated on each successful fetch.
- last_html is available after fetch_and_parse returns.
- Accessing last_html before any fetch raises AttributeError.
"""

from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel

from ports.browser import ScrapingEngine
from ports.scraper import BaseScraper, ScraperConfig


class _Result(BaseModel):
    text: str


class _ConcreteScraper(BaseScraper[_Result]):
    async def parse(self, html: str) -> _Result:
        return _Result(text=html)


class TestLastHtmlProperty:
    async def test_last_html_populated_after_fetch_and_parse(self) -> None:
        """fetch_and_parse sets last_html to the raw HTML returned by the engine."""
        engine = AsyncMock(spec=ScrapingEngine)
        engine.fetch.return_value = "<html>hello</html>"

        scraper = _ConcreteScraper(engine, _make_settings())
        await scraper.fetch_and_parse("https://fbref.com/test/")

        assert scraper.last_html == "<html>hello</html>"

    async def test_last_html_updated_on_second_fetch(self) -> None:
        """last_html reflects the HTML from the most recent fetch_and_parse call."""
        engine = AsyncMock(spec=ScrapingEngine)
        engine.fetch.side_effect = ["<html>first</html>", "<html>second</html>"]

        scraper = _ConcreteScraper(engine, _make_settings())
        await scraper.fetch_and_parse("https://fbref.com/a/")
        await scraper.fetch_and_parse("https://fbref.com/b/")

        assert scraper.last_html == "<html>second</html>"

    def test_last_html_raises_before_first_fetch(self) -> None:
        """Accessing last_html before any fetch raises AttributeError."""
        engine = AsyncMock(spec=ScrapingEngine)
        scraper = _ConcreteScraper(engine, _make_settings())

        with pytest.raises(AttributeError):
            _ = scraper.last_html


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings() -> ScraperConfig:
    """Return a minimal ScraperConfig-compatible settings object."""

    class _Settings:
        max_retries: int = 1
        base_delay: float = 0.0
        max_delay: float = 0.0
        request_delay_min: float = 0.0
        request_delay_max: float = 0.0

    return _Settings()
