"""Unit tests for RemoteCDPEngine — connects to a remote Chromium over CDP/WebSocket.

TDD cycle: RED written first, GREEN in remote_cdp_engine.py.
All pydoll internals and aiohttp calls are mocked — no real browser required.

Design contract:
- _browser is None until first fetch() call (lazy connect).
- Each fetch() opens a fresh tab and closes it after returning HTML.
- close() calls browser.close() (WebSocket disconnect) — NEVER browser.stop().
- _wait_for_challenge() raises PageLoadError after timeout if challenge persists.
- RateLimitError raised when page contains "too many requests".
- PageLoadError raised when go_to() raises PydollException.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.exceptions.scraper import PageLoadError, RateLimitError
from ports.browser import ScrapingEngine

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _html_coroutine(html: str) -> str:
    """Return *html* as a coroutine — mirrors pydoll's async property page_source."""
    return html


def _make_mock_tab(html: str = "<html></html>") -> AsyncMock:
    """Build a mock Tab whose page_source mirrors pydoll's async property."""
    mock_tab = AsyncMock()
    mock_tab.page_source = _html_coroutine(html)
    return mock_tab


def _make_mock_browser(tab: AsyncMock) -> AsyncMock:
    """Build a mock Chrome browser that returns *tab* from connect() and new_tab()."""
    mock_browser = AsyncMock()
    mock_browser.connect = AsyncMock(return_value=tab)
    mock_browser.new_tab = AsyncMock(return_value=tab)
    mock_browser.close = AsyncMock()
    mock_browser.stop = AsyncMock()
    return mock_browser


_DEFAULT_WS_URL = "ws://localhost:9222/devtools/browser/abc"


def _patch_aiohttp_version_endpoint(ws_url: str = _DEFAULT_WS_URL):
    """Return a context manager that patches aiohttp to return *ws_url*."""
    mock_response = AsyncMock()
    mock_response.json = AsyncMock(return_value={"webSocketDebuggerUrl": ws_url})
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_response)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    return patch(
        "infrastructure.browser.remote_cdp_engine.aiohttp.ClientSession",
        return_value=mock_session,
    )


# ---------------------------------------------------------------------------
# Contract: RemoteCDPEngine is a concrete ScrapingEngine
# ---------------------------------------------------------------------------


class TestRemoteCDPEngineIsScrapingEngine:
    def test_is_subclass_of_scraping_engine(self) -> None:
        """RemoteCDPEngine must be a concrete subclass of ScrapingEngine."""
        from infrastructure.browser.remote_cdp_engine import RemoteCDPEngine

        assert issubclass(RemoteCDPEngine, ScrapingEngine)

    def test_can_be_instantiated_with_defaults(self) -> None:
        """RemoteCDPEngine must be instantiable with no arguments."""
        from infrastructure.browser.remote_cdp_engine import RemoteCDPEngine

        engine = RemoteCDPEngine()
        assert engine._browser is None
        assert engine._cdp_host == "localhost"
        assert engine._cdp_port == 9222

    def test_can_be_instantiated_with_custom_host_and_port(self) -> None:
        """RemoteCDPEngine accepts custom cdp_host and cdp_port."""
        from infrastructure.browser.remote_cdp_engine import RemoteCDPEngine

        engine = RemoteCDPEngine(cdp_host="chromium", cdp_port=9223)
        assert engine._cdp_host == "chromium"
        assert engine._cdp_port == 9223


# ---------------------------------------------------------------------------
# T1: Lazy connect on first fetch()
# ---------------------------------------------------------------------------


class TestRemoteCDPEngineLazyConnect:
    async def test_fetch_connects_lazily_on_first_call(self) -> None:
        """_browser is None before fetch(), not None after the first call."""
        from infrastructure.browser.remote_cdp_engine import RemoteCDPEngine

        mock_tab = _make_mock_tab("<html></html>")
        mock_browser = _make_mock_browser(mock_tab)

        with _patch_aiohttp_version_endpoint(), patch(
            "infrastructure.browser.remote_cdp_engine.Chrome",
            return_value=mock_browser,
        ):
            engine = RemoteCDPEngine()
            assert engine._browser is None  # not yet connected

            await engine.fetch("https://example.com")

        assert engine._browser is not None  # connected after fetch

    async def test_second_fetch_does_not_reconnect(self) -> None:
        """A second fetch() must NOT create a new Chrome instance (connection reuse)."""
        from infrastructure.browser.remote_cdp_engine import RemoteCDPEngine

        mock_tab = _make_mock_tab("<html></html>")
        mock_browser = _make_mock_browser(mock_tab)

        with _patch_aiohttp_version_endpoint(), patch(
            "infrastructure.browser.remote_cdp_engine.Chrome",
            return_value=mock_browser,
        ) as mock_chrome_cls:
            engine = RemoteCDPEngine()
            await engine.fetch("https://example.com/page1")
            mock_tab.page_source = _html_coroutine("<html></html>")
            await engine.fetch("https://example.com/page2")

        mock_chrome_cls.assert_called_once()


# ---------------------------------------------------------------------------
# T2: Fresh tab per request
# ---------------------------------------------------------------------------


class TestRemoteCDPEngineFreshTabPerRequest:
    async def test_fetch_opens_and_closes_tab_per_request(self) -> None:
        """browser.new_tab() and tab.close() must each be called once per fetch()."""
        from infrastructure.browser.remote_cdp_engine import RemoteCDPEngine

        mock_tab = _make_mock_tab("<html><body>clean</body></html>")
        mock_browser = _make_mock_browser(mock_tab)

        with _patch_aiohttp_version_endpoint(), patch(
            "infrastructure.browser.remote_cdp_engine.Chrome",
            return_value=mock_browser,
        ):
            engine = RemoteCDPEngine()
            await engine.fetch("https://example.com")

        mock_browser.new_tab.assert_awaited_once()
        mock_tab.close.assert_awaited_once()

    async def test_tab_closed_even_on_pydoll_exception(self) -> None:
        """tab.close() must be called even when go_to() raises PydollException."""
        from pydoll.exceptions import PydollException

        from infrastructure.browser.remote_cdp_engine import RemoteCDPEngine

        mock_tab = AsyncMock()
        mock_tab.go_to = AsyncMock(side_effect=PydollException("network error"))
        mock_tab.close = AsyncMock()

        mock_browser = AsyncMock()
        mock_browser.connect = AsyncMock(return_value=AsyncMock())
        mock_browser.new_tab = AsyncMock(return_value=mock_tab)
        mock_browser.close = AsyncMock()

        with _patch_aiohttp_version_endpoint(), patch(
            "infrastructure.browser.remote_cdp_engine.Chrome",
            return_value=mock_browser,
        ):
            engine = RemoteCDPEngine()
            with pytest.raises(PageLoadError):
                await engine.fetch("https://example.com")

        mock_tab.close.assert_awaited_once()


# ---------------------------------------------------------------------------
# T3: Returns HTML after challenge resolves
# ---------------------------------------------------------------------------


class TestRemoteCDPEngineFetchHtml:
    async def test_fetch_returns_html_after_challenge_resolves(self) -> None:
        """fetch() returns clean HTML when page_source transitions past challenge."""
        from infrastructure.browser.remote_cdp_engine import RemoteCDPEngine

        challenge_html = "<html><title>Just a moment...</title></html>"
        clean_html = "<html><body>Stats content</body></html>"

        call_count = 0

        async def _page_source_side_effect() -> str:
            nonlocal call_count
            call_count += 1
            return challenge_html if call_count == 1 else clean_html

        mock_tab = AsyncMock()
        mock_tab.go_to = AsyncMock()
        mock_tab.close = AsyncMock()
        # page_source is called multiple times — simulate as a regular attribute
        # whose value changes; patch via a property-like side_effect sequence.
        type(mock_tab).page_source = property(  # type: ignore[assignment]
            lambda self: _page_source_side_effect()
        )

        mock_browser = AsyncMock()
        mock_browser.connect = AsyncMock(return_value=AsyncMock())
        mock_browser.new_tab = AsyncMock(return_value=mock_tab)
        mock_browser.close = AsyncMock()

        with _patch_aiohttp_version_endpoint(), patch(
            "infrastructure.browser.remote_cdp_engine.Chrome",
            return_value=mock_browser,
        ), patch(
            "infrastructure.browser.remote_cdp_engine.asyncio.sleep", new=AsyncMock()
        ):
            engine = RemoteCDPEngine()
            result = await engine.fetch("https://fbref.com/")

        assert result == clean_html

    async def test_fetch_returns_html_directly_when_no_challenge(self) -> None:
        """fetch() returns HTML immediately when no challenge markers present."""
        from infrastructure.browser.remote_cdp_engine import RemoteCDPEngine

        clean_html = "<html><body>Player stats</body></html>"
        mock_tab = _make_mock_tab(clean_html)
        mock_browser = _make_mock_browser(mock_tab)

        with _patch_aiohttp_version_endpoint(), patch(
            "infrastructure.browser.remote_cdp_engine.Chrome",
            return_value=mock_browser,
        ):
            engine = RemoteCDPEngine()
            result = await engine.fetch("https://fbref.com/en/players/")

        assert result == clean_html


# ---------------------------------------------------------------------------
# T4: PageLoadError on PydollException
# ---------------------------------------------------------------------------


class TestRemoteCDPEnginePageLoadError:
    async def test_fetch_raises_page_load_error_on_pydoll_exception(self) -> None:
        """go_to() raising PydollException must be translated to PageLoadError."""
        from pydoll.exceptions import PydollException

        from infrastructure.browser.remote_cdp_engine import RemoteCDPEngine

        mock_tab = AsyncMock()
        mock_tab.go_to = AsyncMock(side_effect=PydollException("CDP timeout"))
        mock_tab.close = AsyncMock()

        mock_browser = AsyncMock()
        mock_browser.connect = AsyncMock(return_value=AsyncMock())
        mock_browser.new_tab = AsyncMock(return_value=mock_tab)
        mock_browser.close = AsyncMock()

        with _patch_aiohttp_version_endpoint(), patch(
            "infrastructure.browser.remote_cdp_engine.Chrome",
            return_value=mock_browser,
        ):
            engine = RemoteCDPEngine()
            with pytest.raises(PageLoadError) as exc_info:
                await engine.fetch("https://fbref.com/en/players/")

        assert "fbref.com" in str(exc_info.value)

    async def test_fetch_raises_page_load_error_preserves_url(self) -> None:
        """PageLoadError raised must carry the original URL."""
        from pydoll.exceptions import PydollException

        from infrastructure.browser.remote_cdp_engine import RemoteCDPEngine

        target_url = "https://fbref.com/en/players/stats/123"
        mock_tab = AsyncMock()
        mock_tab.go_to = AsyncMock(side_effect=PydollException("err"))
        mock_tab.close = AsyncMock()

        mock_browser = AsyncMock()
        mock_browser.connect = AsyncMock(return_value=AsyncMock())
        mock_browser.new_tab = AsyncMock(return_value=mock_tab)
        mock_browser.close = AsyncMock()

        with _patch_aiohttp_version_endpoint(), patch(
            "infrastructure.browser.remote_cdp_engine.Chrome",
            return_value=mock_browser,
        ):
            engine = RemoteCDPEngine()
            with pytest.raises(PageLoadError) as exc_info:
                await engine.fetch(target_url)

        assert exc_info.value.url == target_url


# ---------------------------------------------------------------------------
# T5: close() disconnects WebSocket — never stops remote process
# ---------------------------------------------------------------------------


class TestRemoteCDPEngineClose:
    async def test_close_calls_browser_close_not_stop(self) -> None:
        """close() must call browser.close() and NEVER call browser.stop()."""
        from infrastructure.browser.remote_cdp_engine import RemoteCDPEngine

        mock_tab = _make_mock_tab("<html></html>")
        mock_browser = _make_mock_browser(mock_tab)

        with _patch_aiohttp_version_endpoint(), patch(
            "infrastructure.browser.remote_cdp_engine.Chrome",
            return_value=mock_browser,
        ):
            engine = RemoteCDPEngine()
            await engine.fetch("https://example.com")
            await engine.close()

        mock_browser.close.assert_awaited_once()
        mock_browser.stop.assert_not_called()

    async def test_close_resets_internal_state(self) -> None:
        """close() must set _browser and _tab back to None."""
        from infrastructure.browser.remote_cdp_engine import RemoteCDPEngine

        mock_tab = _make_mock_tab("<html></html>")
        mock_browser = _make_mock_browser(mock_tab)

        with _patch_aiohttp_version_endpoint(), patch(
            "infrastructure.browser.remote_cdp_engine.Chrome",
            return_value=mock_browser,
        ):
            engine = RemoteCDPEngine()
            await engine.fetch("https://example.com")
            assert engine._browser is not None
            await engine.close()

        assert engine._browser is None
        assert engine._tab is None

    async def test_close_is_idempotent_when_no_browser(self) -> None:
        """close() must not raise when called before any fetch()."""
        from infrastructure.browser.remote_cdp_engine import RemoteCDPEngine

        engine = RemoteCDPEngine()
        await engine.close()  # should not raise
        assert engine._browser is None


# ---------------------------------------------------------------------------
# T6: _wait_for_challenge raises PageLoadError on timeout
# ---------------------------------------------------------------------------


class TestRemoteCDPEngineChallengeTimeout:
    async def test_wait_for_challenge_raises_on_timeout(self) -> None:
        """_wait_for_challenge must raise PageLoadError if challenge never resolves."""
        from infrastructure.browser.remote_cdp_engine import RemoteCDPEngine

        challenge_html = "<html><title>Just a moment...</title></html>"
        mock_tab = AsyncMock()
        mock_tab.go_to = AsyncMock()
        mock_tab.close = AsyncMock()

        # page_source always returns challenge HTML (never resolves)
        async def _always_challenge() -> str:
            return challenge_html

        type(mock_tab).page_source = property(  # type: ignore[assignment]
            lambda self: _always_challenge()
        )

        mock_browser = AsyncMock()
        mock_browser.connect = AsyncMock(return_value=AsyncMock())
        mock_browser.new_tab = AsyncMock(return_value=mock_tab)
        mock_browser.close = AsyncMock()

        with _patch_aiohttp_version_endpoint(), patch(
            "infrastructure.browser.remote_cdp_engine.Chrome",
            return_value=mock_browser,
        ), patch(
            "infrastructure.browser.remote_cdp_engine._CHALLENGE_TIMEOUT",
            0,  # immediate timeout — no real waiting
        ), patch(
            "infrastructure.browser.remote_cdp_engine.asyncio.sleep",
            new=AsyncMock(),
        ):
            engine = RemoteCDPEngine()
            with pytest.raises(PageLoadError) as exc_info:
                await engine.fetch("https://fbref.com/")

        assert "challenge" in str(exc_info.value).lower()

    async def test_wait_for_challenge_timeout_carries_url(self) -> None:
        """PageLoadError from challenge timeout must carry the original URL."""
        from infrastructure.browser.remote_cdp_engine import RemoteCDPEngine

        target_url = "https://fbref.com/en/players/"

        async def _always_challenge() -> str:
            return "<html><title>Just a moment...</title></html>"

        mock_tab = AsyncMock()
        mock_tab.go_to = AsyncMock()
        mock_tab.close = AsyncMock()
        type(mock_tab).page_source = property(  # type: ignore[assignment]
            lambda self: _always_challenge()
        )

        mock_browser = AsyncMock()
        mock_browser.connect = AsyncMock(return_value=AsyncMock())
        mock_browser.new_tab = AsyncMock(return_value=mock_tab)
        mock_browser.close = AsyncMock()

        with _patch_aiohttp_version_endpoint(), patch(
            "infrastructure.browser.remote_cdp_engine.Chrome",
            return_value=mock_browser,
        ), patch(
            "infrastructure.browser.remote_cdp_engine._CHALLENGE_TIMEOUT",
            0,
        ), patch(
            "infrastructure.browser.remote_cdp_engine.asyncio.sleep",
            new=AsyncMock(),
        ):
            engine = RemoteCDPEngine()
            with pytest.raises(PageLoadError) as exc_info:
                await engine.fetch(target_url)

        assert exc_info.value.url == target_url


# ---------------------------------------------------------------------------
# T7: RateLimitError on rate-limit page
# ---------------------------------------------------------------------------


class TestRemoteCDPEngineRateLimit:
    async def test_fetch_raises_rate_limit_error_on_rate_limit_page(self) -> None:
        """page containing 'too many requests' must raise RateLimitError."""
        from infrastructure.browser.remote_cdp_engine import RemoteCDPEngine

        rate_limit_html = "<html><body><h1>Too Many Requests</h1></body></html>"
        mock_tab = _make_mock_tab(rate_limit_html)
        mock_browser = _make_mock_browser(mock_tab)

        with _patch_aiohttp_version_endpoint(), patch(
            "infrastructure.browser.remote_cdp_engine.Chrome",
            return_value=mock_browser,
        ):
            engine = RemoteCDPEngine()
            with pytest.raises(RateLimitError):
                await engine.fetch("https://fbref.com/")

    async def test_fetch_raises_rate_limit_error_on_rate_limit_text(self) -> None:
        """page containing 'rate limit' must raise RateLimitError."""
        from infrastructure.browser.remote_cdp_engine import RemoteCDPEngine

        rate_limit_html = "<html><body><p>Rate limit exceeded.</p></body></html>"
        mock_tab = _make_mock_tab(rate_limit_html)
        mock_browser = _make_mock_browser(mock_tab)

        with _patch_aiohttp_version_endpoint(), patch(
            "infrastructure.browser.remote_cdp_engine.Chrome",
            return_value=mock_browser,
        ):
            engine = RemoteCDPEngine()
            with pytest.raises(RateLimitError):
                await engine.fetch("https://fbref.com/")

    async def test_clean_html_does_not_raise_rate_limit_error(self) -> None:
        """HTML without rate-limit markers must return content without raising."""
        from infrastructure.browser.remote_cdp_engine import RemoteCDPEngine

        clean_html = "<html><body><p>Player stats here</p></body></html>"
        mock_tab = _make_mock_tab(clean_html)
        mock_browser = _make_mock_browser(mock_tab)

        with _patch_aiohttp_version_endpoint(), patch(
            "infrastructure.browser.remote_cdp_engine.Chrome",
            return_value=mock_browser,
        ):
            engine = RemoteCDPEngine()
            result = await engine.fetch("https://fbref.com/en/players/")

        assert result == clean_html
