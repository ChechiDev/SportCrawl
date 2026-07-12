"""Unit tests for PydollEngine — wraps pydoll-python Chrome browser.

TDD cycle: RED written first, GREEN in pydoll_engine.py.
All pydoll internals are mocked — no real browser required at unit-test time.

Spike findings (task 6.1):
- Chrome(options) → tab = await browser.start() → initial Tab
- await tab.go_to(url) navigates; raises NavigationError / PageLoadTimeout on failure
- await tab.page_source (async property) returns outerHTML string
- await browser.stop() terminates process + closes WebSocket
- PydollException is the base for all pydoll errors
"""

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ports.browser import ScrapingEngine


@pytest.fixture(autouse=True)
def mock_xvfb_start() -> Generator[MagicMock, None, None]:
    """Suppress _XvfbManager.start for all tests — CI has no Xvfb or xdpyinfo."""
    with patch(
        "infrastructure.browser.pydoll_engine._XvfbManager.start"
    ) as mock:
        yield mock

# ---------------------------------------------------------------------------
# Contract: PydollEngine is a concrete ScrapingEngine
# ---------------------------------------------------------------------------


class TestPydollEngineIsScrapingEngine:
    def test_is_subclass_of_scraping_engine(self) -> None:
        """PydollEngine must be a concrete subclass of ScrapingEngine."""
        from infrastructure.browser.pydoll_engine import PydollEngine

        assert issubclass(PydollEngine, ScrapingEngine)

    def test_can_be_instantiated(self) -> None:
        """PydollEngine must be instantiable without arguments."""
        from infrastructure.browser.pydoll_engine import PydollEngine

        engine = PydollEngine()
        assert isinstance(engine, PydollEngine)
        assert engine._browser is None


# ---------------------------------------------------------------------------
# fetch(): happy path — returns HTML string
# ---------------------------------------------------------------------------


async def _html_coroutine(html: str) -> str:
    """Return *html* as a coroutine — mirrors pydoll's ``@property async def
    page_source``."""
    return html


def _make_mock_tab(html: str = "<html></html>") -> AsyncMock:
    """Build a mock Tab whose page_source attribute mirrors pydoll's async property.

    In pydoll, ``@property async def page_source`` means accessing ``tab.page_source``
    returns a coroutine that must be awaited.  We reproduce that by assigning a live
    coroutine object to ``mock_tab.page_source`` so that ``await tab.page_source``
    works exactly as in production code.
    """
    mock_tab = AsyncMock()
    # Assign a coroutine object (not a callable) so ``await tab.page_source`` works.
    mock_tab.page_source = _html_coroutine(html)
    return mock_tab


class TestPydollEngineFetch:
    async def test_fetch_returns_html_string(self) -> None:
        """fetch(url) must return the page HTML as a string."""
        from infrastructure.browser.pydoll_engine import PydollEngine

        mock_tab = _make_mock_tab("<html><body>Hello</body></html>")
        mock_browser = AsyncMock()
        mock_browser.start = AsyncMock(return_value=mock_tab)
        mock_browser.stop = AsyncMock()

        with patch(
            "infrastructure.browser.pydoll_engine.Chrome",
            return_value=mock_browser,
        ):
            engine = PydollEngine()
            html = await engine.fetch("https://example.com")

        assert html == "<html><body>Hello</body></html>"

    async def test_fetch_navigates_to_given_url(self) -> None:
        """fetch(url) must navigate to the exact URL provided."""
        from infrastructure.browser.pydoll_engine import PydollEngine

        mock_tab = _make_mock_tab()
        mock_browser = AsyncMock()
        mock_browser.start = AsyncMock(return_value=mock_tab)
        mock_browser.stop = AsyncMock()

        with patch(
            "infrastructure.browser.pydoll_engine.Chrome",
            return_value=mock_browser,
        ):
            engine = PydollEngine()
            await engine.fetch("https://fbref.com/en/players/")

        mock_tab.go_to.assert_awaited_once_with("https://fbref.com/en/players/")


# ---------------------------------------------------------------------------
# fetch(): pydoll failure → PageLoadError
# ---------------------------------------------------------------------------


class TestPydollEngineFetchError:
    async def test_navigation_error_raises_page_load_error(self) -> None:
        """NavigationError from pydoll must be translated to PageLoadError."""
        from pydoll.exceptions import NavigationError as PydollNavigationError

        from core.exceptions.scraper import PageLoadError
        from infrastructure.browser.pydoll_engine import PydollEngine

        mock_tab = AsyncMock()
        mock_tab.go_to = AsyncMock(
            side_effect=PydollNavigationError(
                url="https://bad.example.com", error_text="net::ERR_NAME_NOT_RESOLVED"
            )
        )

        mock_browser = AsyncMock()
        mock_browser.start = AsyncMock(return_value=mock_tab)
        mock_browser.stop = AsyncMock()

        with patch(
            "infrastructure.browser.pydoll_engine.Chrome",
            return_value=mock_browser,
        ):
            engine = PydollEngine()
            with pytest.raises(PageLoadError) as exc_info:
                await engine.fetch("https://bad.example.com")

        assert "https://bad.example.com" in str(exc_info.value)
        mock_browser.stop.assert_awaited_once()
        assert engine._browser is None
        assert engine._tab is None

    async def test_page_load_timeout_raises_page_load_error(self) -> None:
        """PageLoadTimeout from pydoll must be translated to PageLoadError."""
        from pydoll.exceptions import PageLoadTimeout as PydollPageLoadTimeout

        from core.exceptions.scraper import PageLoadError
        from infrastructure.browser.pydoll_engine import PydollEngine

        mock_tab = AsyncMock()
        mock_tab.go_to = AsyncMock(side_effect=PydollPageLoadTimeout())

        mock_browser = AsyncMock()
        mock_browser.start = AsyncMock(return_value=mock_tab)
        mock_browser.stop = AsyncMock()

        with patch(
            "infrastructure.browser.pydoll_engine.Chrome",
            return_value=mock_browser,
        ):
            engine = PydollEngine()
            with pytest.raises(PageLoadError) as exc_info:
                await engine.fetch("https://slow.example.com")

        assert "https://slow.example.com" in str(exc_info.value)
        mock_browser.stop.assert_awaited_once()
        assert engine._browser is None
        assert engine._tab is None


# ---------------------------------------------------------------------------
# close(): delegates to browser.stop()
# ---------------------------------------------------------------------------


class TestPydollEngineClose:
    async def test_close_stops_browser(self) -> None:
        """close() must call browser.stop() to release CDP resources."""
        from infrastructure.browser.pydoll_engine import PydollEngine

        mock_tab = _make_mock_tab()
        mock_browser = AsyncMock()
        mock_browser.start = AsyncMock(return_value=mock_tab)
        mock_browser.stop = AsyncMock()

        with patch(
            "infrastructure.browser.pydoll_engine.Chrome",
            return_value=mock_browser,
        ):
            engine = PydollEngine()
            # Trigger browser creation via fetch first
            await engine.fetch("https://example.com")
            await engine.close()

        mock_browser.stop.assert_awaited_once()
        assert engine._browser is None
        assert engine._tab is None

    async def test_close_is_idempotent_when_no_browser(self) -> None:
        """close() must not raise when called before any fetch (no browser started)."""
        from infrastructure.browser.pydoll_engine import PydollEngine

        engine = PydollEngine()
        # Should not raise
        await engine.close()
        assert engine._browser is None


# ---------------------------------------------------------------------------
# fetch(): 429 / rate-limit heuristic detection
# ---------------------------------------------------------------------------


class TestPydollEngineRateLimitDetection:
    async def test_too_many_requests_text_raises_rate_limit_error(self) -> None:
        """429 as numeric data (not rate-limit marker) passes through."""
        from core.exceptions.scraper import RateLimitError
        from infrastructure.browser.pydoll_engine import PydollEngine

        mock_tab = AsyncMock()
        mock_tab.go_to = AsyncMock()
        mock_tab.page_source = _html_coroutine(
            "<html><body><h1>Too Many Requests</h1></body></html>"
        )
        mock_browser = AsyncMock()
        mock_browser.start = AsyncMock(return_value=mock_tab)
        mock_browser.stop = AsyncMock()

        with patch(
            "infrastructure.browser.pydoll_engine.Chrome",
            return_value=mock_browser,
        ):
            engine = PydollEngine()
            with pytest.raises(RateLimitError):
                await engine.fetch("https://fbref.com/")

    async def test_clean_html_passes_through_without_raising(self) -> None:
        """page_source with no 429 markers returns the HTML string normally."""
        from infrastructure.browser.pydoll_engine import PydollEngine

        expected = "<html><body><p>Clean stats content</p></body></html>"
        mock_tab = _make_mock_tab(expected)
        mock_browser = AsyncMock()
        mock_browser.start = AsyncMock(return_value=mock_tab)
        mock_browser.stop = AsyncMock()

        with patch(
            "infrastructure.browser.pydoll_engine.Chrome",
            return_value=mock_browser,
        ):
            engine = PydollEngine()
            result = await engine.fetch("https://fbref.com/")

        assert result == expected

    async def test_page_with_429_as_numeric_stat_does_not_raise(self) -> None:
        """429 as numeric data (not rate-limit marker) passes through."""
        from infrastructure.browser.pydoll_engine import PydollEngine

        html_with_stat = (
            "<html><body>"
            "<table><tr><th>Passes</th><td>429</td></tr></table>"
            "</body></html>"
        )
        mock_tab = AsyncMock()
        mock_tab.go_to = AsyncMock()
        mock_tab.page_source = _html_coroutine(html_with_stat)
        mock_browser = AsyncMock()
        mock_browser.start = AsyncMock(return_value=mock_tab)
        mock_browser.stop = AsyncMock()

        with patch(
            "infrastructure.browser.pydoll_engine.Chrome",
            return_value=mock_browser,
        ):
            engine = PydollEngine()
            result = await engine.fetch("https://fbref.com/")

        assert result == html_with_stat

    async def test_pydoll_exception_raises_page_load_error_not_rate_limit(
        self,
    ) -> None:
        """PydollException from go_to() maps to PageLoadError, not RateLimitError."""
        from pydoll.exceptions import PydollException

        from core.exceptions.scraper import PageLoadError
        from infrastructure.browser.pydoll_engine import PydollEngine

        mock_tab = AsyncMock()
        mock_tab.go_to = AsyncMock(side_effect=PydollException("network error"))
        mock_browser = AsyncMock()
        mock_browser.start = AsyncMock(return_value=mock_tab)
        mock_browser.stop = AsyncMock()

        with patch(
            "infrastructure.browser.pydoll_engine.Chrome",
            return_value=mock_browser,
        ):
            engine = PydollEngine()
            with pytest.raises(PageLoadError):
                await engine.fetch("https://fbref.com/")


# ---------------------------------------------------------------------------
# Lazy-init: Chrome() instantiated only once across multiple fetch() calls
# ---------------------------------------------------------------------------


class TestPydollEngineLazyInit:
    async def test_fetch_reuses_existing_browser(self) -> None:
        """A second fetch() must NOT create a new Chrome instance (lazy-init reuse)."""
        from infrastructure.browser.pydoll_engine import PydollEngine

        mock_tab = _make_mock_tab("<html></html>")
        mock_browser = AsyncMock()
        mock_browser.start = AsyncMock(return_value=mock_tab)
        mock_browser.stop = AsyncMock()

        with patch(
            "infrastructure.browser.pydoll_engine.Chrome",
            return_value=mock_browser,
        ) as mock_chrome_cls:
            engine = PydollEngine()
            await engine.fetch("https://example.com/page1")
            # Coroutines are consumed after one await; refresh for the second call.
            mock_tab.page_source = _html_coroutine("<html></html>")
            await engine.fetch("https://example.com/page2")

        mock_chrome_cls.assert_called_once()
