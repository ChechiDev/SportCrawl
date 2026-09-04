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
                coro, timeout=timeout, **kw
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
        config = {
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
