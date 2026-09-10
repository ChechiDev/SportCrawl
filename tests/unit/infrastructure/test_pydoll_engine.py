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
    """Suppress XvfbDisplay.start for all tests — CI has no Xvfb or xdpyinfo."""
    with patch("infrastructure.browser.xvfb_display.XvfbDisplay.start") as mock:
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


# ---------------------------------------------------------------------------
# Display ownership: shared vs engine-owned
# ---------------------------------------------------------------------------


class TestPydollEngineDisplayOwnership:
    def test_no_display_arg_creates_owned_display(self) -> None:
        """Engine created without a display arg must own its own XvfbDisplay."""
        from infrastructure.browser.pydoll_engine import PydollEngine

        engine = PydollEngine()
        assert engine._display_owned is True
        assert engine._display is not None

    def test_display_arg_sets_borrowed(self) -> None:
        """Engine created with a display arg must NOT own it."""
        from infrastructure.browser.pydoll_engine import PydollEngine
        from infrastructure.browser.xvfb_display import XvfbDisplay

        shared = XvfbDisplay()
        engine = PydollEngine(display=shared)
        assert engine._display_owned is False
        assert engine._display is shared

    async def test_close_stops_owned_display(self) -> None:
        """close() must stop the display when the engine owns it."""
        from infrastructure.browser.pydoll_engine import PydollEngine

        engine = PydollEngine()
        mock_browser = MagicMock()
        mock_browser.stop = AsyncMock()
        engine._browser = mock_browser
        engine._tab = MagicMock()

        with patch.object(engine._display, "stop") as mock_stop:
            await engine.close()
            mock_stop.assert_called_once()

    async def test_close_does_not_stop_borrowed_display(self) -> None:
        """close() must NOT stop the display when it is borrowed."""
        from infrastructure.browser.pydoll_engine import PydollEngine
        from infrastructure.browser.xvfb_display import XvfbDisplay

        shared = XvfbDisplay()
        engine = PydollEngine(display=shared)
        mock_browser = MagicMock()
        mock_browser.stop = AsyncMock()
        engine._browser = mock_browser
        engine._tab = MagicMock()

        with patch.object(shared, "stop") as mock_stop:
            await engine.close()
            mock_stop.assert_not_called()

    def test_existing_callers_remain_compatible(self) -> None:
        """PydollEngine() with no display arg must still work (backward compat)."""
        from infrastructure.browser.pydoll_engine import PydollEngine

        # All existing callers pass only profile_dir and/or name
        engine1 = PydollEngine()
        engine2 = PydollEngine(profile_dir="/tmp/test")
        engine3 = PydollEngine(name="worker-1")
        engine4 = PydollEngine(profile_dir="/tmp/test", name="worker-1")

        for e in (engine1, engine2, engine3, engine4):
            assert e._display_owned is True

    async def test_close_stops_owned_display_when_no_browser_started(self) -> None:
        """close() must stop owned display even when no browser was ever started."""
        from infrastructure.browser.pydoll_engine import PydollEngine

        engine = PydollEngine()
        # _browser stays None — engine never opened a browser

        with patch.object(engine._display, "stop") as mock_stop:
            await engine.close()
            mock_stop.assert_called_once()


# ---------------------------------------------------------------------------
# start(): explicit browser initialisation
# ---------------------------------------------------------------------------


_CHROME_PATCH = "infrastructure.browser.pydoll_engine.Chrome"


class TestPydollEngineStart:
    @pytest.fixture
    def mock_browser_and_tab(
        self,
    ) -> Generator[tuple[AsyncMock, AsyncMock], None, None]:
        mock_tab = _make_mock_tab("<html></html>")
        mock_browser = AsyncMock()
        mock_browser.start = AsyncMock(return_value=mock_tab)
        mock_browser.stop = AsyncMock()
        with patch(_CHROME_PATCH, return_value=mock_browser):
            yield mock_browser, mock_tab

    async def test_start_initialises_browser(
        self, mock_browser_and_tab: tuple[AsyncMock, AsyncMock]
    ) -> None:
        """start() must create a Chrome instance and set _browser."""
        from infrastructure.browser.pydoll_engine import PydollEngine

        mock_browser, _ = mock_browser_and_tab
        engine = PydollEngine()
        await engine.start()

        assert engine._browser is mock_browser

    async def test_start_sets_active_tab(
        self, mock_browser_and_tab: tuple[AsyncMock, AsyncMock]
    ) -> None:
        """start() must set _tab after Chrome.start() resolves."""
        from infrastructure.browser.pydoll_engine import PydollEngine

        _, mock_tab = mock_browser_and_tab
        engine = PydollEngine()
        await engine.start()

        assert engine._tab is mock_tab

    async def test_start_is_idempotent_browser_created_once(
        self, mock_browser_and_tab: tuple[AsyncMock, AsyncMock]
    ) -> None:
        """start() called twice must NOT create duplicate Chrome instances."""
        from infrastructure.browser.pydoll_engine import PydollEngine

        mock_browser, _ = mock_browser_and_tab
        engine = PydollEngine()
        await engine.start()
        await engine.start()

        # browser.start() (the pydoll Tab-factory method) called exactly once
        mock_browser.start.assert_awaited_once()

    async def test_start_is_idempotent_tab_created_once(
        self, mock_browser_and_tab: tuple[AsyncMock, AsyncMock]
    ) -> None:
        """start() called twice must NOT create duplicate tabs."""
        from infrastructure.browser.pydoll_engine import PydollEngine

        mock_browser, _ = mock_browser_and_tab
        engine = PydollEngine()
        await engine.start()
        first_tab = engine._tab
        await engine.start()

        assert engine._tab is first_tab
        mock_browser.start.assert_awaited_once()

    async def test_navigate_works_after_explicit_start(
        self, mock_browser_and_tab: tuple[AsyncMock, AsyncMock]
    ) -> None:
        """navigate() must still work after start() (backward compat)."""
        from infrastructure.browser.pydoll_engine import PydollEngine

        _, mock_tab = mock_browser_and_tab
        mock_tab.page_source = _html_coroutine("<html></html>")
        engine = PydollEngine()
        await engine.start()
        await engine.navigate("https://fbref.com/")

        mock_tab.go_to.assert_awaited_once_with("https://fbref.com/")


# ---------------------------------------------------------------------------
# warmup(): browser readiness probe
# ---------------------------------------------------------------------------


class TestPydollEngineWarmup:
    async def test_warmup_succeeds_with_non_empty_html(self) -> None:
        """warmup(url) must succeed when page returns non-empty HTML."""
        from infrastructure.browser.pydoll_engine import PydollEngine

        mock_tab = _make_mock_tab()
        mock_browser = AsyncMock()
        mock_browser.start = AsyncMock(return_value=mock_tab)
        mock_browser.stop = AsyncMock()

        with patch(_CHROME_PATCH, return_value=mock_browser):
            engine = PydollEngine()
            engine.navigate = AsyncMock()
            engine._wait_for_challenge = AsyncMock(
                return_value="<html><body>FBRef</body></html>"
            )

            # Must not raise
            await engine.warmup("https://fbref.com")

        engine.navigate.assert_awaited_once_with("https://fbref.com")
        engine._wait_for_challenge.assert_awaited_once_with(
            engine._tab, "https://fbref.com"
        )
        assert engine._browser is not None

    async def test_warmup_calls_navigate(self) -> None:
        """warmup(url) must call navigate() with the readiness_url."""
        from infrastructure.browser.pydoll_engine import PydollEngine

        mock_tab = _make_mock_tab()
        mock_browser = AsyncMock()
        mock_browser.start = AsyncMock(return_value=mock_tab)
        mock_browser.stop = AsyncMock()

        with patch(_CHROME_PATCH, return_value=mock_browser):
            engine = PydollEngine()
            engine.navigate = AsyncMock()
            engine._wait_for_challenge = AsyncMock(return_value="<html>ok</html>")

            await engine.warmup("https://fbref.com")

        engine.navigate.assert_awaited_once_with("https://fbref.com")

    async def test_warmup_calls_wait_for_challenge(self) -> None:
        """warmup(url) must call _wait_for_challenge() after navigate()."""
        from infrastructure.browser.pydoll_engine import PydollEngine

        mock_tab = _make_mock_tab()
        mock_browser = AsyncMock()
        mock_browser.start = AsyncMock(return_value=mock_tab)
        mock_browser.stop = AsyncMock()

        with patch(_CHROME_PATCH, return_value=mock_browser):
            engine = PydollEngine()
            engine.navigate = AsyncMock()
            challenge_mock = AsyncMock(return_value="<html>ok</html>")
            engine._wait_for_challenge = challenge_mock

            await engine.warmup("https://fbref.com")

        # _wait_for_challenge receives (tab, url) — tab is engine._tab
        challenge_mock.assert_awaited_once_with(engine._tab, "https://fbref.com")

    async def test_warmup_raises_warmup_error_on_navigate_failure(self) -> None:
        """warmup(url) must raise WarmupError when navigate() raises PageLoadError."""
        from core.exceptions.scraper import PageLoadError, WarmupError
        from infrastructure.browser.pydoll_engine import PydollEngine

        mock_tab = _make_mock_tab()
        mock_browser = AsyncMock()
        mock_browser.start = AsyncMock(return_value=mock_tab)
        mock_browser.stop = AsyncMock()

        with patch(_CHROME_PATCH, return_value=mock_browser):
            engine = PydollEngine()
            engine.navigate = AsyncMock(
                side_effect=PageLoadError("nav failed", url="https://fbref.com")
            )

            with pytest.raises(WarmupError):
                await engine.warmup("https://fbref.com")

    async def test_warmup_raises_warmup_error_on_challenge_failure(self) -> None:
        """warmup(url) raises WarmupError when _wait_for_challenge() fails."""
        from core.exceptions.scraper import PageLoadError, WarmupError
        from infrastructure.browser.pydoll_engine import PydollEngine

        mock_tab = _make_mock_tab()
        mock_browser = AsyncMock()
        mock_browser.start = AsyncMock(return_value=mock_tab)
        mock_browser.stop = AsyncMock()

        with patch(_CHROME_PATCH, return_value=mock_browser):
            engine = PydollEngine()
            engine.navigate = AsyncMock()
            engine._wait_for_challenge = AsyncMock(
                side_effect=PageLoadError("cf timeout", url="https://fbref.com")
            )

            with pytest.raises(WarmupError):
                await engine.warmup("https://fbref.com")

    async def test_warmup_raises_warmup_error_on_empty_response(self) -> None:
        """warmup(url) must raise WarmupError when HTML response is empty."""
        from core.exceptions.scraper import WarmupError
        from infrastructure.browser.pydoll_engine import PydollEngine

        mock_tab = _make_mock_tab()
        mock_browser = AsyncMock()
        mock_browser.start = AsyncMock(return_value=mock_tab)
        mock_browser.stop = AsyncMock()

        with patch(_CHROME_PATCH, return_value=mock_browser):
            engine = PydollEngine()
            engine.navigate = AsyncMock()
            engine._wait_for_challenge = AsyncMock(return_value="")

            with pytest.raises(WarmupError):
                await engine.warmup("https://fbref.com")

    async def test_warmup_raises_warmup_error_on_whitespace_only_response(
        self,
    ) -> None:
        """warmup(url) must raise WarmupError when response is whitespace-only."""
        from core.exceptions.scraper import WarmupError
        from infrastructure.browser.pydoll_engine import PydollEngine

        mock_tab = _make_mock_tab()
        mock_browser = AsyncMock()
        mock_browser.start = AsyncMock(return_value=mock_tab)
        mock_browser.stop = AsyncMock()

        with patch(_CHROME_PATCH, return_value=mock_browser):
            engine = PydollEngine()
            engine.navigate = AsyncMock()
            engine._wait_for_challenge = AsyncMock(return_value="   \n  ")

            with pytest.raises(WarmupError):
                await engine.warmup("https://fbref.com")

    async def test_warmup_error_is_subclass_of_page_load_error(self) -> None:
        """WarmupError must be a subclass of PageLoadError."""
        from core.exceptions.scraper import PageLoadError, WarmupError

        assert issubclass(WarmupError, PageLoadError)

    async def test_warmup_calls_start_first(self) -> None:
        """warmup() must call start() to guarantee browser is initialised."""
        from infrastructure.browser.pydoll_engine import PydollEngine

        mock_tab = _make_mock_tab()
        mock_browser = AsyncMock()
        mock_browser.start = AsyncMock(return_value=mock_tab)
        mock_browser.stop = AsyncMock()

        with patch(_CHROME_PATCH, return_value=mock_browser):
            engine = PydollEngine()
            # Do NOT call start() before warmup — warmup must do it
            assert engine._browser is None
            engine.navigate = AsyncMock()
            engine._wait_for_challenge = AsyncMock(return_value="<html>ok</html>")

            await engine.warmup("https://fbref.com")

        assert engine._browser is mock_browser


# ---------------------------------------------------------------------------
# inject_storage_config(): structured CDP callFunctionOn injection
# ---------------------------------------------------------------------------


class TestPydollEngineInjectStorageConfig:
    async def test_raises_page_load_error_when_tab_is_none(self) -> None:
        """inject_storage_config() must raise PageLoadError if the tab is not ready."""
        from core.exceptions.scraper import PageLoadError
        from infrastructure.browser.pydoll_engine import PydollEngine

        engine = PydollEngine()
        assert engine._tab is None

        with pytest.raises(PageLoadError, match="inject_storage_config"):
            await engine.inject_storage_config({"key": "value"})

    async def test_calls_execute_command_with_call_function_on(self) -> None:
        """inject_storage_config() must use callFunctionOn so config values are
        structured CDP arguments, never embedded in the JS function body string."""
        from infrastructure.browser.pydoll_engine import PydollEngine

        mock_tab = AsyncMock()
        mock_tab._execute_command = AsyncMock(return_value={"result": {"value": True}})
        mock_tab.go_to = AsyncMock()
        mock_tab.page_source = _html_coroutine("<html></html>")
        mock_browser = AsyncMock()
        mock_browser.start = AsyncMock(return_value=mock_tab)

        sentinel_token = "SENTINEL_SECRET_TOKEN_VALUE"
        config = {
            "work_server_url": "http://127.0.0.1:9731",
            "work_server_token": sentinel_token,
            "profile_id": "smoke",
            "worker_id": "smoke",
            "disable_task_polling": True,
        }

        with patch(
            "infrastructure.browser.pydoll_engine.Chrome",
            return_value=mock_browser,
        ):
            engine = PydollEngine()
            await engine.start()
            await engine.inject_storage_config(config)

        mock_tab._execute_command.assert_awaited_once()
        cmd = mock_tab._execute_command.call_args[0][0]
        # The CDP command method must be Runtime.callFunctionOn
        assert cmd.get("method") == "Runtime.callFunctionOn"
        # The function declaration (JS string) must NOT contain the secret token
        fn_decl = cmd.get("params", {}).get("functionDeclaration", "")
        assert sentinel_token not in fn_decl, (
            "Token must not appear in the JS function declaration string"
        )

    async def test_raises_page_load_error_on_cdp_failure(self) -> None:
        """inject_storage_config() must raise PageLoadError on CDP exceptions."""
        from pydoll.exceptions import PydollException

        from core.exceptions.scraper import PageLoadError
        from infrastructure.browser.pydoll_engine import PydollEngine

        mock_tab = AsyncMock()
        mock_tab._execute_command = AsyncMock(side_effect=PydollException("CDP error"))
        mock_tab.go_to = AsyncMock()
        mock_tab.page_source = _html_coroutine("<html></html>")
        mock_browser = AsyncMock()
        mock_browser.start = AsyncMock(return_value=mock_tab)

        with patch(
            "infrastructure.browser.pydoll_engine.Chrome",
            return_value=mock_browser,
        ):
            engine = PydollEngine()
            await engine.start()

            with pytest.raises(PageLoadError, match="inject_storage_config"):
                await engine.inject_storage_config({"key": "value"})

    async def test_times_out_and_raises_page_load_error_when_cdp_hangs(self) -> None:
        """inject_storage_config() must call asyncio.wait_for with timeout=15.0.

        Verified by mocking asyncio.wait_for so the internal 15s timeout
        contract is enforced regardless of the outer test guard.
        """
        import asyncio as _asyncio

        from infrastructure.browser import pydoll_engine as _engine_mod
        from infrastructure.browser.pydoll_engine import PydollEngine

        mock_tab = AsyncMock()
        mock_tab._execute_command = AsyncMock(return_value={"result": {"value": True}})
        mock_tab.go_to = AsyncMock()
        mock_tab.page_source = _html_coroutine("<html></html>")
        mock_browser = AsyncMock()
        mock_browser.start = AsyncMock(return_value=mock_tab)

        captured_timeout: list[float] = []
        _real_wait_for = _asyncio.wait_for

        async def _spy_wait_for(
            coro: object, *, timeout: float, **kw: object
        ) -> object:
            captured_timeout.append(timeout)
            return await _real_wait_for(  # type: ignore[arg-type]
                coro, timeout=timeout, **kw  # type: ignore[arg-type]
            )

        with patch(
            "infrastructure.browser.pydoll_engine.Chrome",
            return_value=mock_browser,
        ), patch.object(_engine_mod.asyncio, "wait_for", side_effect=_spy_wait_for):
            engine = PydollEngine()
            await engine.start()
            await engine.inject_storage_config({"key": "value"})

        assert captured_timeout == [15.0], (
            f"inject_storage_config must use timeout=15.0, got {captured_timeout}"
        )

    async def test_times_out_and_raises_page_load_error_via_timeout_error(self) -> None:
        """inject_storage_config() wraps asyncio.TimeoutError as PageLoadError."""

        from core.exceptions.scraper import PageLoadError
        from infrastructure.browser.pydoll_engine import PydollEngine

        mock_tab = AsyncMock()
        mock_tab._execute_command = AsyncMock(side_effect=TimeoutError())
        mock_tab.go_to = AsyncMock()
        mock_tab.page_source = _html_coroutine("<html></html>")
        mock_browser = AsyncMock()
        mock_browser.start = AsyncMock(return_value=mock_tab)

        with patch(
            "infrastructure.browser.pydoll_engine.Chrome",
            return_value=mock_browser,
        ):
            engine = PydollEngine()
            await engine.start()

            with pytest.raises(PageLoadError, match="inject_storage_config"):
                await engine.inject_storage_config({"key": "value"})

    async def test_wraps_attribute_error_as_page_load_error(self) -> None:
        """AttributeError from pydoll API change must not escape as unhandled."""
        from core.exceptions.scraper import PageLoadError
        from infrastructure.browser.pydoll_engine import PydollEngine

        mock_tab = AsyncMock()
        mock_tab._execute_command = AsyncMock(side_effect=AttributeError("renamed"))
        mock_tab.go_to = AsyncMock()
        mock_tab.page_source = _html_coroutine("<html></html>")
        mock_browser = AsyncMock()
        mock_browser.start = AsyncMock(return_value=mock_tab)

        with patch(
            "infrastructure.browser.pydoll_engine.Chrome",
            return_value=mock_browser,
        ):
            engine = PydollEngine()
            await engine.start()

            with pytest.raises(PageLoadError, match="inject_storage_config"):
                await engine.inject_storage_config({"key": "value"})


# ---------------------------------------------------------------------------
# inject_storage_config_to_extension() — SW target CDP injection
# ---------------------------------------------------------------------------


class TestPydollEngineInjectStorageConfigToExtension:
    """Tests for inject_storage_config_to_extension() — injects via the
    extension's service-worker CDP session, not the main tab context.
    """

    @staticmethod
    def _make_sw_fake_execute(
        sw_target_id: str = "sw-target-1",
        sw_url: str = "chrome-extension://abc123/background.js",
        session_id: str = "session-abc",
        object_id: str = "obj-1",
    ):
        """Return an async side_effect that fakes SW CDP round-trips."""

        async def _fake(cmd: dict) -> dict:
            method = cmd.get("method", "")
            if method == "Target.getTargets":
                return {
                    "result": {
                        "targetInfos": [
                            {
                                "targetId": sw_target_id,
                                "type": "service_worker",
                                "url": sw_url,
                            }
                        ]
                    }
                }
            if method == "Target.attachToTarget":
                return {"result": {"sessionId": session_id}}
            if method == "Runtime.evaluate":
                return {"result": {"result": {"objectId": object_id}}}
            if method == "Runtime.callFunctionOn":
                return {"result": {"result": {"value": True}}}
            if method == "Target.detachFromTarget":
                return {}
            return {}

        return _fake

    async def test_raises_page_load_error_when_tab_is_none(self) -> None:
        from core.exceptions.scraper import PageLoadError
        from infrastructure.browser.pydoll_engine import PydollEngine

        engine = PydollEngine()
        assert engine._tab is None

        with pytest.raises(PageLoadError):
            await engine.inject_storage_config_to_extension({"key": "value"})

    async def test_raises_page_load_error_when_no_extension_sw_target_found(
        self,
    ) -> None:
        from core.exceptions.scraper import PageLoadError
        from infrastructure.browser.pydoll_engine import PydollEngine

        async def _fake_execute(cmd: dict) -> dict:
            if cmd.get("method") == "Target.getTargets":
                return {
                    "result": {
                        "targetInfos": [
                            {
                                "targetId": "page-1",
                                "type": "page",
                                "url": "https://example.com",
                            }
                        ]
                    }
                }
            return {}

        mock_tab = AsyncMock()
        mock_tab._execute_command = AsyncMock(side_effect=_fake_execute)

        engine = PydollEngine()
        engine._tab = mock_tab

        with pytest.raises(PageLoadError):
            await engine.inject_storage_config_to_extension({"key": "value"})

    async def test_sends_get_targets_command(self) -> None:
        from infrastructure.browser.pydoll_engine import PydollEngine

        mock_tab = AsyncMock()
        mock_tab._execute_command = AsyncMock(
            side_effect=self._make_sw_fake_execute()
        )

        engine = PydollEngine()
        engine._tab = mock_tab

        await engine.inject_storage_config_to_extension({"key": "value"})

        calls = mock_tab._execute_command.call_args_list
        methods = [c[0][0].get("method") for c in calls]
        assert "Target.getTargets" in methods

    async def test_attaches_to_extension_sw_target(self) -> None:
        from infrastructure.browser.pydoll_engine import PydollEngine

        mock_tab = AsyncMock()
        mock_tab._execute_command = AsyncMock(
            side_effect=self._make_sw_fake_execute(sw_target_id="sw-target-1")
        )

        engine = PydollEngine()
        engine._tab = mock_tab

        await engine.inject_storage_config_to_extension({"key": "value"})

        calls = mock_tab._execute_command.call_args_list
        attach_calls = [
            c for c in calls if c[0][0].get("method") == "Target.attachToTarget"
        ]
        assert len(attach_calls) == 1
        params = attach_calls[0][0][0].get("params", {})
        assert params.get("targetId") == "sw-target-1"

    async def test_calls_function_on_sw_context_not_tab_context(self) -> None:
        from infrastructure.browser.pydoll_engine import PydollEngine

        mock_tab = AsyncMock()
        mock_tab._execute_command = AsyncMock(
            side_effect=self._make_sw_fake_execute(session_id="session-abc")
        )

        engine = PydollEngine()
        engine._tab = mock_tab

        await engine.inject_storage_config_to_extension({"key": "value"})

        calls = mock_tab._execute_command.call_args_list
        call_fn_calls = [
            c for c in calls if c[0][0].get("method") == "Runtime.callFunctionOn"
        ]
        assert len(call_fn_calls) == 1
        cmd = call_fn_calls[0][0][0]
        assert cmd.get("sessionId") == "session-abc", (
            f"callFunctionOn must carry the SW session ID, got cmd={cmd}"
        )

    async def test_token_not_in_js_function_body(self) -> None:
        from infrastructure.browser.pydoll_engine import PydollEngine

        sentinel = "SENTINEL_SECRET_TOKEN_ABC123"
        config: dict[str, object] = {
            "work_server_url": "http://127.0.0.1:9731",
            "work_server_token": sentinel,
            "profile_id": "smoke",
            "worker_id": "smoke",
        }

        mock_tab = AsyncMock()
        mock_tab._execute_command = AsyncMock(
            side_effect=self._make_sw_fake_execute()
        )

        engine = PydollEngine()
        engine._tab = mock_tab

        await engine.inject_storage_config_to_extension(config)

        for call in mock_tab._execute_command.call_args_list:
            cmd = call[0][0]
            fn_decl = cmd.get("params", {}).get("functionDeclaration", "")
            assert sentinel not in fn_decl, (
                f"Token sentinel must not appear in functionDeclaration. cmd={cmd}"
            )

    async def test_raises_page_load_error_when_attach_returns_no_session_id(
        self,
    ) -> None:
        """If Target.attachToTarget returns no sessionId, PageLoadError is raised.

        An empty sessionId would silently route CDP commands to the wrong context
        (main session or nowhere), causing config injection to appear to succeed
        when the SW was never configured. The guard must prevent this.
        """
        from core.exceptions.scraper import PageLoadError
        from infrastructure.browser.pydoll_engine import PydollEngine

        async def _fake_no_session(cmd: dict) -> dict:
            method = cmd.get("method", "")
            if method == "Target.getTargets":
                return {
                    "result": {
                        "targetInfos": [
                            {
                                "targetId": "sw-1",
                                "type": "service_worker",
                                "url": "chrome-extension://abc/background.js",
                            }
                        ]
                    }
                }
            if method == "Target.attachToTarget":
                # sessionId absent — malformed or partial CDP failure
                return {"result": {}}
            return {}

        mock_tab = AsyncMock()
        mock_tab._execute_command = AsyncMock(side_effect=_fake_no_session)
        engine = PydollEngine()
        engine._tab = mock_tab

        with pytest.raises(PageLoadError):
            await engine.inject_storage_config_to_extension({"key": "value"})

    # -----------------------------------------------------------------------
    # F2: no-SW-target path retries exactly _SW_TARGET_RETRIES times
    # -----------------------------------------------------------------------

    async def test_retries_get_targets_exactly_sw_target_retries_times(self) -> None:
        """When getTargets never returns a SW target, it is called exactly
        _SW_TARGET_RETRIES times before PageLoadError is raised.

        Guards against regressions that reduce or skip retries silently.
        """
        import infrastructure.browser.pydoll_engine as _eng_mod
        from core.exceptions.scraper import PageLoadError
        from infrastructure.browser.pydoll_engine import PydollEngine

        async def _no_sw_target(cmd: dict) -> dict:
            if cmd.get("method") == "Target.getTargets":
                return {"result": {"targetInfos": []}}
            return {}

        mock_tab = AsyncMock()
        mock_tab._execute_command = AsyncMock(side_effect=_no_sw_target)

        engine = PydollEngine()
        engine._tab = mock_tab

        with patch.object(_eng_mod, "_SW_TARGET_RETRY_DELAY_S", 0.0):
            with pytest.raises(PageLoadError):
                await engine.inject_storage_config_to_extension({"key": "value"})

        get_targets_calls = [
            c
            for c in mock_tab._execute_command.call_args_list
            if c[0][0].get("method") == "Target.getTargets"
        ]
        assert len(get_targets_calls) == _eng_mod._SW_TARGET_RETRIES, (
            f"Expected {_eng_mod._SW_TARGET_RETRIES} getTargets attempts, "
            f"got {len(get_targets_calls)}"
        )

    # -----------------------------------------------------------------------
    # F1: getTargets exception propagates immediately — no retry, no detach
    # -----------------------------------------------------------------------

    async def test_get_targets_exception_propagates_without_retry(self) -> None:
        """If Target.getTargets raises, the exception propagates immediately.

        The retry loop only retries when the target is not found — it must not
        swallow or retry on transport/CDP failures.
        """
        from core.exceptions.scraper import PageLoadError
        from infrastructure.browser.pydoll_engine import PydollEngine

        call_count = 0

        async def _raises_on_get_targets(cmd: dict) -> dict:
            nonlocal call_count
            if cmd.get("method") == "Target.getTargets":
                call_count += 1
                raise KeyError("simulated CDP failure on getTargets")
            return {}

        mock_tab = AsyncMock()
        mock_tab._execute_command = AsyncMock(
            side_effect=_raises_on_get_targets
        )

        engine = PydollEngine()
        engine._tab = mock_tab

        with pytest.raises(PageLoadError):
            await engine.inject_storage_config_to_extension({"key": "value"})

        assert call_count == 1, (
            f"getTargets exception must not be retried — "
            f"expected 1 call, got {call_count}"
        )
        detach_calls = [
            c
            for c in mock_tab._execute_command.call_args_list
            if c[0][0].get("method") == "Target.detachFromTarget"
        ]
        assert len(detach_calls) == 0, (
            "detach must not be attempted if attach never happened"
        )

    # -----------------------------------------------------------------------
    # F3: detach failure does not mask the original post-attach failure
    # -----------------------------------------------------------------------

    async def test_detach_failure_does_not_mask_original_error(self) -> None:
        """If Target.detachFromTarget itself raises, the original error propagates.

        The try/except Exception in the finally block must swallow detach
        errors — the caller must see the original failure from steps 3/4.
        """
        from core.exceptions.scraper import PageLoadError
        from infrastructure.browser.pydoll_engine import PydollEngine

        async def _fail_evaluate_and_detach(cmd: dict) -> dict:
            method = cmd.get("method", "")
            if method == "Target.getTargets":
                return {
                    "result": {
                        "targetInfos": [
                            {
                                "targetId": "sw-1",
                                "type": "service_worker",
                                "url": "chrome-extension://abc/background.js",
                            }
                        ]
                    }
                }
            if method == "Target.attachToTarget":
                return {"result": {"sessionId": "session-xyz"}}
            if method == "Target.detachFromTarget":
                raise OSError("detach transport error")
            raise KeyError("simulated failure at evaluate")

        mock_tab = AsyncMock()
        mock_tab._execute_command = AsyncMock(
            side_effect=_fail_evaluate_and_detach
        )

        engine = PydollEngine()
        engine._tab = mock_tab

        # Original error (KeyError → PageLoadError) must propagate despite detach error
        with pytest.raises(PageLoadError):
            await engine.inject_storage_config_to_extension({"key": "value"})

    # -----------------------------------------------------------------------
    # F4: cancellation after attach still attempts detach
    # -----------------------------------------------------------------------

    async def test_cancellation_after_attach_still_attempts_detach(self) -> None:
        """If the coroutine is cancelled while a post-attach step is awaited,
        the finally block still runs and Target.detachFromTarget is attempted.
        """
        import asyncio as _asyncio

        from infrastructure.browser.pydoll_engine import PydollEngine

        detach_attempted: list[str] = []

        async def _cancel_at_evaluate(cmd: dict) -> dict:
            method = cmd.get("method", "")
            if method == "Target.getTargets":
                return {
                    "result": {
                        "targetInfos": [
                            {
                                "targetId": "sw-1",
                                "type": "service_worker",
                                "url": "chrome-extension://abc/background.js",
                            }
                        ]
                    }
                }
            if method == "Target.attachToTarget":
                return {"result": {"sessionId": "session-cancel"}}
            if method == "Target.detachFromTarget":
                detach_attempted.append(
                    cmd.get("params", {}).get("sessionId", "")
                )
                return {}
            # Runtime.evaluate — raise CancelledError to simulate cancellation
            raise _asyncio.CancelledError()

        mock_tab = AsyncMock()
        mock_tab._execute_command = AsyncMock(
            side_effect=_cancel_at_evaluate
        )

        engine = PydollEngine()
        engine._tab = mock_tab

        with pytest.raises((_asyncio.CancelledError, Exception)):
            await engine.inject_storage_config_to_extension({"key": "value"})

        assert detach_attempted == ["session-cancel"], (
            "Target.detachFromTarget must be attempted after cancellation "
            f"with the correct session ID; got: {detach_attempted}"
        )

    async def test_detaches_session_on_success(self) -> None:
        """Target.detachFromTarget must be called after successful injection."""
        from infrastructure.browser.pydoll_engine import PydollEngine

        mock_tab = AsyncMock()
        mock_tab._execute_command = AsyncMock(
            side_effect=self._make_sw_fake_execute(session_id="session-abc")
        )

        engine = PydollEngine()
        engine._tab = mock_tab

        await engine.inject_storage_config_to_extension({"key": "value"})

        calls = mock_tab._execute_command.call_args_list
        detach_calls = [
            c for c in calls if c[0][0].get("method") == "Target.detachFromTarget"
        ]
        assert len(detach_calls) == 1
        params = detach_calls[0][0][0].get("params", {})
        assert params.get("sessionId") == "session-abc"

    async def test_detaches_session_on_failure_after_attach(self) -> None:
        """Target.detachFromTarget must be called even when steps 3/4 fail."""
        from core.exceptions.scraper import PageLoadError
        from infrastructure.browser.pydoll_engine import PydollEngine

        async def _fake_fail_at_evaluate(cmd: dict) -> dict:
            method = cmd.get("method", "")
            if method == "Target.getTargets":
                return {
                    "result": {
                        "targetInfos": [
                            {
                                "targetId": "sw-1",
                                "type": "service_worker",
                                "url": "chrome-extension://abc/background.js",
                            }
                        ]
                    }
                }
            if method == "Target.attachToTarget":
                return {"result": {"sessionId": "session-xyz"}}
            if method == "Target.detachFromTarget":
                return {}
            raise KeyError("simulated CDP failure at evaluate")

        mock_tab = AsyncMock()
        mock_tab._execute_command = AsyncMock(side_effect=_fake_fail_at_evaluate)

        engine = PydollEngine()
        engine._tab = mock_tab

        with pytest.raises(PageLoadError):
            await engine.inject_storage_config_to_extension({"key": "value"})

        calls = mock_tab._execute_command.call_args_list
        detach_calls = [
            c for c in calls if c[0][0].get("method") == "Target.detachFromTarget"
        ]
        assert len(detach_calls) == 1
        params = detach_calls[0][0][0].get("params", {})
        assert params.get("sessionId") == "session-xyz"

    async def test_raises_page_load_error_when_evaluate_returns_no_object_id(
        self,
    ) -> None:
        """If Runtime.evaluate returns no objectId, PageLoadError is raised.

        An empty objectId would cause callFunctionOn to target nothing, silently
        dropping the write. The guard must catch this before proceeding to Step 4.
        """
        from core.exceptions.scraper import PageLoadError
        from infrastructure.browser.pydoll_engine import PydollEngine

        async def _fake_no_object_id(cmd: dict) -> dict:
            method = cmd.get("method", "")
            if method == "Target.getTargets":
                return {
                    "result": {
                        "targetInfos": [
                            {
                                "targetId": "sw-1",
                                "type": "service_worker",
                                "url": "chrome-extension://abc/background.js",
                            }
                        ]
                    }
                }
            if method == "Target.attachToTarget":
                return {"result": {"sessionId": "session-abc"}}
            if method == "Runtime.evaluate":
                # objectId absent — SW context not accessible
                return {"result": {"result": {}}}
            return {}

        mock_tab = AsyncMock()
        mock_tab._execute_command = AsyncMock(side_effect=_fake_no_object_id)
        engine = PydollEngine()
        engine._tab = mock_tab

        with pytest.raises(PageLoadError):
            await engine.inject_storage_config_to_extension({"key": "value"})

    # -----------------------------------------------------------------------
    # WU8-A: exceptionDetails in callFunctionOn raises PageLoadError
    # -----------------------------------------------------------------------

    async def test_exception_details_in_call_function_on_raises_page_load_error(
        self,
    ) -> None:
        """If callFunctionOn CDP response contains exceptionDetails, PageLoadError."""
        from core.exceptions.scraper import PageLoadError
        from infrastructure.browser.pydoll_engine import PydollEngine

        call_count = 0

        async def _fake_with_exception(cmd: dict) -> dict:
            nonlocal call_count
            method = cmd.get("method", "")
            if method == "Target.getTargets":
                return {
                    "result": {
                        "targetInfos": [
                            {
                                "targetId": "sw-1",
                                "type": "service_worker",
                                "url": "chrome-extension://abc/background.js",
                            }
                        ]
                    }
                }
            if method == "Target.attachToTarget":
                return {"result": {"sessionId": "session-abc"}}
            if method == "Runtime.evaluate":
                return {"result": {"result": {"objectId": "obj-1"}}}
            if method == "Runtime.callFunctionOn":
                call_count += 1
                if call_count == 1:
                    return {
                        "result": {
                            "result": {"type": "undefined"},
                            "exceptionDetails": {
                                "text": (
                                    "chrome.runtime.lastError:"
                                    " Extension context invalidated"
                                ),
                                "exception": {"type": "object"},
                            },
                        }
                    }
                return {"result": {"result": {"value": True}}}
            if method == "Target.detachFromTarget":
                return {}
            return {}

        mock_tab = AsyncMock()
        mock_tab._execute_command = AsyncMock(side_effect=_fake_with_exception)
        engine = PydollEngine()
        engine._tab = mock_tab

        with pytest.raises(PageLoadError, match="exceptionDetails"):
            await engine.inject_storage_config_to_extension(
                {"allowed_clearance_domain": "example.com"}
            )

    # -----------------------------------------------------------------------
    # WU8-B: post-injection readback — success (matching domain)
    # -----------------------------------------------------------------------

    async def test_post_injection_readback_success(self) -> None:
        """After write, engine reads back allowed_clearance_domain and succeeds."""
        from infrastructure.browser.pydoll_engine import PydollEngine

        call_count = 0

        async def _fake_readback_match(cmd: dict) -> dict:
            nonlocal call_count
            method = cmd.get("method", "")
            if method == "Target.getTargets":
                return {
                    "result": {
                        "targetInfos": [
                            {
                                "targetId": "sw-1",
                                "type": "service_worker",
                                "url": "chrome-extension://abc/background.js",
                            }
                        ]
                    }
                }
            if method == "Target.attachToTarget":
                return {"result": {"sessionId": "session-abc"}}
            if method == "Runtime.evaluate":
                return {"result": {"result": {"objectId": "obj-1"}}}
            if method == "Runtime.callFunctionOn":
                call_count += 1
                if call_count == 1:
                    return {"result": {"result": {"value": True}}}
                return {
                    "result": {
                        "result": {
                            "value": {"allowed_clearance_domain": "example.com"}
                        }
                    }
                }
            if method == "Target.detachFromTarget":
                return {}
            return {}

        mock_tab = AsyncMock()
        mock_tab._execute_command = AsyncMock(side_effect=_fake_readback_match)
        engine = PydollEngine()
        engine._tab = mock_tab

        await engine.inject_storage_config_to_extension(
            {"allowed_clearance_domain": "example.com"}
        )
        assert call_count == 2, (
            f"Expected 2 callFunctionOn calls (write + readback), got {call_count}"
        )

    # -----------------------------------------------------------------------
    # WU8-B2: no readback when allowed_clearance_domain absent — exactly 1 call
    # -----------------------------------------------------------------------

    async def test_no_readback_when_domain_not_in_config(self) -> None:
        """When config does NOT contain allowed_clearance_domain, exactly one
        Runtime.callFunctionOn call is made (the write, not the readback)."""
        from infrastructure.browser.pydoll_engine import PydollEngine

        mock_tab = AsyncMock()
        mock_tab._execute_command = AsyncMock(
            side_effect=self._make_sw_fake_execute()
        )

        engine = PydollEngine()
        engine._tab = mock_tab

        await engine.inject_storage_config_to_extension({"key": "value"})

        call_fn_calls = [
            c
            for c in mock_tab._execute_command.call_args_list
            if c[0][0].get("method") == "Runtime.callFunctionOn"
        ]
        assert len(call_fn_calls) == 1, (
            f"Expected exactly 1 callFunctionOn (write only, no readback),"
            f" got {len(call_fn_calls)}"
        )

    # -----------------------------------------------------------------------
    # WU8-C: post-injection readback — mismatch raises PageLoadError
    # -----------------------------------------------------------------------

    async def test_post_injection_readback_mismatch_raises(self) -> None:
        """When readback returns a different domain, PageLoadError is raised."""
        from core.exceptions.scraper import PageLoadError
        from infrastructure.browser.pydoll_engine import PydollEngine

        call_count = 0

        async def _fake_readback_mismatch(cmd: dict) -> dict:
            nonlocal call_count
            method = cmd.get("method", "")
            if method == "Target.getTargets":
                return {
                    "result": {
                        "targetInfos": [
                            {
                                "targetId": "sw-1",
                                "type": "service_worker",
                                "url": "chrome-extension://abc/background.js",
                            }
                        ]
                    }
                }
            if method == "Target.attachToTarget":
                return {"result": {"sessionId": "session-abc"}}
            if method == "Runtime.evaluate":
                return {"result": {"result": {"objectId": "obj-1"}}}
            if method == "Runtime.callFunctionOn":
                call_count += 1
                if call_count == 1:
                    return {"result": {"result": {"value": True}}}
                return {
                    "result": {
                        "result": {
                            "value": {"allowed_clearance_domain": "wrong.com"}
                        }
                    }
                }
            if method == "Target.detachFromTarget":
                return {}
            return {}

        mock_tab = AsyncMock()
        mock_tab._execute_command = AsyncMock(side_effect=_fake_readback_mismatch)
        engine = PydollEngine()
        engine._tab = mock_tab

        with pytest.raises(PageLoadError, match="readback"):
            await engine.inject_storage_config_to_extension(
                {"allowed_clearance_domain": "example.com"}
            )

    # -----------------------------------------------------------------------
    # WU8-D: post-injection readback — empty object raises PageLoadError
    # -----------------------------------------------------------------------

    async def test_post_injection_readback_missing_key_raises(self) -> None:
        """When readback returns {}, PageLoadError is raised."""
        from core.exceptions.scraper import PageLoadError
        from infrastructure.browser.pydoll_engine import PydollEngine

        call_count = 0

        async def _fake_readback_empty(cmd: dict) -> dict:
            nonlocal call_count
            method = cmd.get("method", "")
            if method == "Target.getTargets":
                return {
                    "result": {
                        "targetInfos": [
                            {
                                "targetId": "sw-1",
                                "type": "service_worker",
                                "url": "chrome-extension://abc/background.js",
                            }
                        ]
                    }
                }
            if method == "Target.attachToTarget":
                return {"result": {"sessionId": "session-abc"}}
            if method == "Runtime.evaluate":
                return {"result": {"result": {"objectId": "obj-1"}}}
            if method == "Runtime.callFunctionOn":
                call_count += 1
                if call_count == 1:
                    return {"result": {"result": {"value": True}}}
                return {"result": {"result": {"value": {}}}}
            if method == "Target.detachFromTarget":
                return {}
            return {}

        mock_tab = AsyncMock()
        mock_tab._execute_command = AsyncMock(side_effect=_fake_readback_empty)
        engine = PydollEngine()
        engine._tab = mock_tab

        with pytest.raises(PageLoadError, match="readback"):
            await engine.inject_storage_config_to_extension(
                {"allowed_clearance_domain": "example.com"}
            )


# ---------------------------------------------------------------------------
# read_extension_storage_diagnostic() — sanitized diagnostic reads
# ---------------------------------------------------------------------------


class TestPydollEngineReadExtensionStorageDiagnostic:
    """Tests for read_extension_storage_diagnostic() — best-effort, sanitized."""

    @staticmethod
    def _make_diagnostic_fake(
        key: str,
        stored_value: object | None,
        sw_url: str = "chrome-extension://abc123/background.js",
    ):
        """Return async side_effect faking SW CDP round-trips for diagnostic reads."""

        async def _fake(cmd: dict) -> dict:
            method = cmd.get("method", "")
            if method == "Target.getTargets":
                return {
                    "result": {
                        "targetInfos": [
                            {
                                "targetId": "sw-diag-1",
                                "type": "service_worker",
                                "url": sw_url,
                            }
                        ]
                    }
                }
            if method == "Target.attachToTarget":
                return {"result": {"sessionId": "session-diag"}}
            if method == "Runtime.evaluate":
                return {"result": {"result": {"objectId": "obj-diag"}}}
            if method == "Runtime.callFunctionOn":
                if stored_value is None:
                    return {"result": {"result": {"value": {}}}}
                return {"result": {"result": {"value": {key: stored_value}}}}
            if method == "Target.detachFromTarget":
                return {}
            return {}

        return _fake

    # -----------------------------------------------------------------------
    # WU8-E: sanitized read — success, returns only safe subset
    # -----------------------------------------------------------------------

    async def test_diagnostic_read_returns_sanitized_subset(self) -> None:
        """read_extension_storage_diagnostic returns only the safe subset of fields."""
        from infrastructure.browser.pydoll_engine import PydollEngine

        raw_value = {
            "attempted": True,
            "drop_reason": "payload_too_large",
            "error_class": "ValidationError",
            "http_status_class": "4xx",
            # sensitive fields that must NOT be returned
            "raw_body": "<html>secret</html>",
            "cookie": "session=abc123",
            "token": "Bearer xyz",
            "url": "https://example.com/clearance",
        }

        mock_tab = AsyncMock()
        mock_tab._execute_command = AsyncMock(
            side_effect=self._make_diagnostic_fake(
                "last_clearance_post_status", raw_value
            )
        )
        engine = PydollEngine()
        engine._tab = mock_tab

        result = await engine.read_extension_storage_diagnostic(
            "last_clearance_post_status"
        )

        assert result is not None
        assert result.get("attempted") is True
        assert result.get("drop_reason") == "payload_too_large"
        assert result.get("error_class") == "ValidationError"
        assert result.get("http_status_class") == "4xx"
        assert "raw_body" not in result
        assert "cookie" not in result
        assert "token" not in result
        assert "url" not in result

    # -----------------------------------------------------------------------
    # WU8-E2: falsy-dict bug — {"attempted": False} must not return None
    # -----------------------------------------------------------------------

    async def test_diagnostic_read_returns_dict_with_falsy_values(self) -> None:
        """read_extension_storage_diagnostic must not treat {"attempted": False}
        as falsy and return None — the dict itself is valid even when values are
        falsy booleans."""
        from infrastructure.browser.pydoll_engine import PydollEngine

        raw_value = {"attempted": False}

        mock_tab = AsyncMock()
        mock_tab._execute_command = AsyncMock(
            side_effect=self._make_diagnostic_fake(
                "last_clearance_post_status", raw_value
            )
        )
        engine = PydollEngine()
        engine._tab = mock_tab

        result = await engine.read_extension_storage_diagnostic(
            "last_clearance_post_status"
        )

        assert result is not None, (
            "A dict with falsy values like {'attempted': False} must not be "
            "treated as None — the {} or None bug"
        )
        assert result.get("attempted") is False

    # -----------------------------------------------------------------------
    # WU8-F: sanitized read — key absent returns None
    # -----------------------------------------------------------------------

    async def test_diagnostic_read_key_absent_returns_none(self) -> None:
        """read_extension_storage_diagnostic returns None when key not in storage."""
        from infrastructure.browser.pydoll_engine import PydollEngine

        mock_tab = AsyncMock()
        mock_tab._execute_command = AsyncMock(
            side_effect=self._make_diagnostic_fake("last_clearance_post_status", None)
        )
        engine = PydollEngine()
        engine._tab = mock_tab

        result = await engine.read_extension_storage_diagnostic(
            "last_clearance_post_status"
        )
        assert result is None

    # -----------------------------------------------------------------------
    # WU8-G: no SW target — returns None (does not raise)
    # -----------------------------------------------------------------------

    async def test_diagnostic_read_no_sw_target_returns_none(self) -> None:
        """read_extension_storage_diagnostic returns None when no SW target found."""
        from infrastructure.browser.pydoll_engine import PydollEngine

        async def _no_sw(cmd: dict) -> dict:
            if cmd.get("method") == "Target.getTargets":
                return {"result": {"targetInfos": []}}
            return {}

        mock_tab = AsyncMock()
        mock_tab._execute_command = AsyncMock(side_effect=_no_sw)
        engine = PydollEngine()
        engine._tab = mock_tab

        result = await engine.read_extension_storage_diagnostic(
            "last_clearance_post_status"
        )
        assert result is None
