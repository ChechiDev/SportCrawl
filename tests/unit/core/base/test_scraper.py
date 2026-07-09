"""Tests for BaseScraper ABC with fetch/parse separation and retry/backoff logic.

Uses MockEngine (in-file concrete ScrapingEngine). No real browser.
asyncio.sleep is patched to avoid real waits.
"""

from typing import Any
from unittest.mock import AsyncMock, patch

import pandas as pd
import pytest
from pydantic import BaseModel

from config.settings import ScrapingSettings
from core.exceptions.scraper import (
    PageLoadError,
    ParsingError,
    RateLimitError,
    ScraperError,
)
from ports.browser import ScrapingEngine
from ports.scraper import BaseScraper, BaseMultiTableScraper

# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class MockEngine(ScrapingEngine):
    """Minimal concrete engine for tests — returns a fixed HTML string."""

    async def fetch(self, url: str) -> str:
        return "<html>ok</html>"

    async def close(self) -> None:
        pass


class _ParseResult(BaseModel):
    content: str


class ConcreteScraper(BaseScraper[_ParseResult]):
    """Minimal concrete scraper — parse returns a _ParseResult."""

    async def parse(self, html: str) -> _ParseResult:
        return _ParseResult(content=html)


# Generic test doubles
class MyModel(BaseModel):
    text: str


class MyScraper(BaseScraper[MyModel]):
    async def parse(self, html: str) -> MyModel:
        return MyModel(text=html)


# BaseMultiTableScraper test doubles
class TableResult(BaseModel):
    table_ids: list[str]


class ConcreteMultiScraper(BaseMultiTableScraper[TableResult]):
    async def parse_tables(self, tables: dict[str, pd.DataFrame]) -> TableResult:
        return TableResult(table_ids=list(tables.keys()))


def _settings(**overrides: Any) -> ScrapingSettings:
    """Build ScrapingSettings with safe test defaults."""
    base: dict[str, Any] = {
        "max_retries": 3,
        "base_delay": 1.0,
        "max_delay": 60.0,
        "request_timeout": 30,
    }
    base.update(overrides)
    return ScrapingSettings(**base)


# ---------------------------------------------------------------------------
# Instantiation
# ---------------------------------------------------------------------------


class TestInstantiation:
    def test_base_scraper_cannot_be_instantiated_directly(self) -> None:
        """BaseScraper is abstract because of the parse() abstract method."""
        with pytest.raises(TypeError):
            BaseScraper(MockEngine(), _settings())  # type: ignore[abstract]

    def test_concrete_subclass_can_be_instantiated(self) -> None:
        scraper = ConcreteScraper(MockEngine(), _settings())
        assert isinstance(scraper, BaseScraper)


# ---------------------------------------------------------------------------
# Generic[T_co] constraint
# ---------------------------------------------------------------------------


class TestGenericConstraint:
    async def test_typed_scraper_returns_t_co_instance(self) -> None:
        """fetch_and_parse returns the concrete T_co, not bare BaseModel."""
        engine = AsyncMock(spec=ScrapingEngine)
        engine.fetch.return_value = "<html>hello</html>"

        scraper = MyScraper(engine, _settings())
        result = await scraper.fetch_and_parse("https://fbref.com/")

        assert isinstance(result, MyModel)
        assert result.text == "<html>hello</html>"

    def test_typed_scraper_is_base_scraper_subtype(self) -> None:
        assert issubclass(MyScraper, BaseScraper)


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------


class TestSuccessPath:
    async def test_parse_is_called_with_html_returned_by_engine(self) -> None:
        engine = AsyncMock(spec=ScrapingEngine)
        engine.fetch.return_value = "<html>data</html>"

        scraper = ConcreteScraper(engine, _settings())
        result = await scraper.fetch_and_parse("https://example.com")

        engine.fetch.assert_called_once_with("https://example.com")
        assert isinstance(result, _ParseResult)
        assert result.content == "<html>data</html>"

    async def test_returns_result_on_success_after_one_failure(self) -> None:
        """If the engine fails once then succeeds, the parse result is returned."""
        engine = AsyncMock(spec=ScrapingEngine)
        engine.fetch.side_effect = [
            PageLoadError("transient", url="https://example.com"),
            "<html>recovered</html>",
        ]

        with patch("asyncio.sleep", new_callable=AsyncMock):
            scraper = ConcreteScraper(engine, _settings(max_retries=3))
            result = await scraper.fetch_and_parse("https://example.com")

        assert isinstance(result, _ParseResult)
        assert engine.fetch.call_count == 2


# ---------------------------------------------------------------------------
# Retry loop
# ---------------------------------------------------------------------------


class TestRetryLoop:
    async def test_engine_called_max_retries_times_when_always_failing(self) -> None:
        """With max_retries=3, fetch is called exactly 3 times before raising."""
        engine = AsyncMock(spec=ScrapingEngine)
        engine.fetch.side_effect = PageLoadError("fail", url="https://example.com")

        with patch("asyncio.sleep", new_callable=AsyncMock):
            scraper = ConcreteScraper(engine, _settings(max_retries=3))
            with pytest.raises(ScraperError):
                await scraper.fetch_and_parse("https://example.com")

        assert engine.fetch.call_count == 3

    async def test_scraper_error_raised_after_retry_exhaustion(self) -> None:
        """A ScraperError subtype — not bare Exception — is raised after exhaustion."""
        engine = AsyncMock(spec=ScrapingEngine)
        engine.fetch.side_effect = PageLoadError("fail", url="https://example.com")

        with patch("asyncio.sleep", new_callable=AsyncMock):
            scraper = ConcreteScraper(engine, _settings(max_retries=2))
            with pytest.raises(ScraperError):
                await scraper.fetch_and_parse("https://example.com")

    async def test_rate_limit_error_is_retried(self) -> None:
        """RateLimitError triggers the retry path, not an immediate raise."""
        engine = AsyncMock(spec=ScrapingEngine)
        engine.fetch.side_effect = RateLimitError("429", url="https://example.com")

        with patch("asyncio.sleep", new_callable=AsyncMock):
            scraper = ConcreteScraper(engine, _settings(max_retries=2))
            with pytest.raises(ScraperError):
                await scraper.fetch_and_parse("https://example.com")

        assert engine.fetch.call_count == 2


# ---------------------------------------------------------------------------
# Exponential backoff
# ---------------------------------------------------------------------------


class TestExponentialBackoff:
    async def test_sleep_delay_increases_on_each_retry(self) -> None:
        """Delay must grow exponentially: base_delay * 2^(attempt-1)."""
        engine = AsyncMock(spec=ScrapingEngine)
        engine.fetch.side_effect = PageLoadError("fail", url="https://example.com")

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            scraper = ConcreteScraper(
                engine,
                _settings(max_retries=3, base_delay=1.0, max_delay=60.0),
            )
            with pytest.raises(ScraperError):
                await scraper.fetch_and_parse("https://example.com")

        # max_retries=3: sleep after attempt 1 and 2; no sleep after final failure.
        assert mock_sleep.call_count == 2
        delays = [c.args[0] for c in mock_sleep.call_args_list]
        assert delays[0] < delays[1], "each wait must be longer than the previous"

    async def test_sleep_delay_capped_at_max_delay(self) -> None:
        """Computed delay must never exceed max_delay."""
        engine = AsyncMock(spec=ScrapingEngine)
        engine.fetch.side_effect = PageLoadError("fail", url="https://example.com")

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            scraper = ConcreteScraper(
                engine,
                _settings(max_retries=3, base_delay=100.0, max_delay=5.0),
            )
            with pytest.raises(ScraperError):
                await scraper.fetch_and_parse("https://example.com")

        delays = [c.args[0] for c in mock_sleep.call_args_list]
        assert all(d <= 5.0 for d in delays)


# ---------------------------------------------------------------------------
# Error propagation
# ---------------------------------------------------------------------------


class TestErrorPropagation:
    async def test_parsing_error_propagates_immediately_without_retry(self) -> None:
        """ParsingError from parse() is re-raised without triggering the retry loop."""
        engine = AsyncMock(spec=ScrapingEngine)
        engine.fetch.return_value = "<html>bad</html>"

        scraper = ConcreteScraper(engine, _settings(max_retries=3))
        scraper.parse = AsyncMock(  # type: ignore[method-assign]
            side_effect=ParsingError("parse failed")
        )

        with pytest.raises(ParsingError):
            await scraper.fetch_and_parse("https://example.com")

        # Only 1 fetch; ParsingError is not retried.
        assert engine.fetch.call_count == 1


# ---------------------------------------------------------------------------
# BaseMultiTableScraper
# ---------------------------------------------------------------------------

HTML_TWO_ID_TABLES = """
<html><body>
<table id="stats_standard"><tr><th>A</th></tr><tr><td>1</td></tr></table>
<table id="stats_shooting"><tr><th>B</th></tr><tr><td>2</td></tr></table>
</body></html>
"""

HTML_ONE_ID_ONE_NO_ID = """
<html><body>
<table id="stats_standard"><tr><th>A</th></tr><tr><td>1</td></tr></table>
<table><tr><th>B</th></tr><tr><td>2</td></tr></table>
</body></html>
"""

HTML_NO_ID_TABLE = """
<html><body>
<table><tr><th>C</th></tr><tr><td>3</td></tr></table>
</body></html>
"""

HTML_NO_TABLES = "<html><body><p>no tables here</p></body></html>"


class TestBaseMultiTableScraper:
    async def test_two_id_tables_are_keyed_by_id(self) -> None:
        """parse() returns a dict keyed by each table's HTML id attribute."""
        engine = AsyncMock(spec=ScrapingEngine)
        engine.fetch.return_value = HTML_TWO_ID_TABLES

        scraper = ConcreteMultiScraper(engine, _settings())
        result = await scraper.fetch_and_parse("https://fbref.com/")

        assert isinstance(result, TableResult)
        assert "stats_standard" in result.table_ids
        assert "stats_shooting" in result.table_ids
        assert len(result.table_ids) == 2

    async def test_table_without_id_is_skipped(self) -> None:
        """Tables missing the id attribute are not included in the dict."""
        engine = AsyncMock(spec=ScrapingEngine)
        engine.fetch.return_value = HTML_ONE_ID_ONE_NO_ID

        scraper = ConcreteMultiScraper(engine, _settings())
        result = await scraper.fetch_and_parse("https://fbref.com/")

        assert result.table_ids == ["stats_standard"]

    async def test_no_id_table_raises_scraper_error(self) -> None:
        """A page with tables but none having id raises ScraperError, not ValueError."""
        engine = AsyncMock(spec=ScrapingEngine)
        engine.fetch.return_value = HTML_NO_ID_TABLE

        scraper = ConcreteMultiScraper(engine, _settings())
        with pytest.raises(ScraperError, match="no tables with id attribute found"):
            await scraper.fetch_and_parse("https://fbref.com/")

    async def test_page_with_no_tables_raises_scraper_error(self) -> None:
        """A page with no <table> elements at all raises ScraperError."""
        engine = AsyncMock(spec=ScrapingEngine)
        engine.fetch.return_value = HTML_NO_TABLES

        scraper = ConcreteMultiScraper(engine, _settings())
        with pytest.raises(ScraperError):
            await scraper.fetch_and_parse("https://fbref.com/")

    def test_base_multi_table_scraper_is_abstract(self) -> None:
        """Cannot instantiate BaseMultiTableScraper without parse_tables."""
        with pytest.raises(TypeError):
            BaseMultiTableScraper(MockEngine(), _settings())  # type: ignore[abstract]
