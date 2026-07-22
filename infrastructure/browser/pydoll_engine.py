"""Concrete ScrapingEngine implementation backed by pydoll-python (Chrome/CDP).

Spike findings (task 6.1):
- Chrome(options) is the concrete browser class.
- tab = await browser.start() returns the initial Tab.
- await tab.go_to(url) navigates; raises NavigationError or PageLoadTimeout on failure.
- await tab.page_source (async property) returns document.documentElement.outerHTML.
- await browser.stop() terminates the browser process and closes the WebSocket.
- PydollException is the base class for all pydoll library errors.

Design contract:
- PydollEngine lazily creates a Chrome browser on first fetch() call.
- close() stops the browser and resets internal state.
- Any pydoll exception during navigation is translated to PageLoadError.
- The sportcrawl Chrome extension is loaded automatically if present under
  extensions/sportcrawl-chrome/ (MV3, unpacked). The extension improves
  browser fingerprinting and captures cf_clearance cookies for the work_server.
- After navigation, _wait_for_challenge() polls page_source until Cloudflare's
  "Just a moment..." challenge resolves (or raises PageLoadError on timeout).
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from pydoll.browser.chromium.chrome import Chrome
from pydoll.exceptions import PydollException

from core.exceptions.scraper import PageLoadError, RateLimitError
from ports.browser import ScriptableEngine

logger = logging.getLogger(__name__)

_XVFB_DISPLAY = ":199"


class _XvfbManager:
    """Manages a background Xvfb process so Chrome never opens a visible window.

    Always uses display :199 (unlikely to conflict with system displays or WSLg).
    Cleans up any stale socket before starting.
    """

    def __init__(self) -> None:
        self._proc: subprocess.Popen[bytes] | None = None

    @staticmethod
    def _display_alive(display: str) -> bool:
        """Return True if an X server is already listening on *display*."""
        try:
            result = subprocess.run(
                ["xdpyinfo", "-display", display],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=2,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def start(self) -> None:
        """Point DISPLAY at a virtual framebuffer — Chrome never opens a visible window.

        Safe to call when Xvfb or xdpyinfo are not installed (CI environments).
        """
        if self._proc is not None:
            return  # already managed by us

        os.environ["DISPLAY"] = _XVFB_DISPLAY

        if self._display_alive(_XVFB_DISPLAY):
            # An X server is already listening on :199 — reuse it
            return

        try:
            self._proc = subprocess.Popen(
                ["Xvfb", _XVFB_DISPLAY, "-screen", "0", "1920x1080x24"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            logger.debug(
                "Xvfb not found — Chrome will use existing DISPLAY or run headless"
            )
            return
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if self._display_alive(_XVFB_DISPLAY):
                break
            time.sleep(0.1)

    def stop(self) -> None:
        """Terminate Xvfb and restore the environment."""
        if self._proc is not None:
            self._proc.terminate()
            self._proc = None
            os.environ.pop("DISPLAY", None)


_CHALLENGE_MARKERS = ("just a moment", "checking your browser")
_EXTENSION_PATH = Path(__file__).parents[2] / "extensions" / "sportcrawl-chrome"
_CHALLENGE_TIMEOUT = 120  # seconds — Turnstile managed challenge can take 30–90s


class PydollEngine(ScriptableEngine):
    """ScrapingEngine that drives Chrome via CDP using pydoll-python.

    The browser is started lazily on the first fetch() call and must be
    explicitly released via close(), or used as an async context manager.
    """

    def __init__(self, profile_dir: str | None = None, name: str = "engine") -> None:
        self._browser: Chrome | None = None
        # pydoll Tab type is not exported; using Any until upstream types stabilize
        self._tab: Any = None
        self._xvfb: _XvfbManager = _XvfbManager()
        self._profile_dir: str = profile_dir or "/tmp/sportcrawl-chrome-profile"
        self._name = name
        self._keepalive_task: asyncio.Task[None] | None = None

    async def __aenter__(self) -> PydollEngine:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    @staticmethod
    def _clear_profile_lock(profile_dir: str) -> None:
        lock = Path(profile_dir) / "SingletonLock"
        try:
            lock.unlink()
            logger.debug("Removed stale Chrome SingletonLock at %s", lock)
        except FileNotFoundError:
            pass

    async def _ensure_browser(self) -> None:
        """Lazily initialize the Chrome browser and its initial tab."""
        if self._browser is None:
            logger.debug("Starting Chrome browser (lazy init)")
            await asyncio.to_thread(self._xvfb.start)

            _profile = self._profile_dir
            self._clear_profile_lock(_profile)

            import os

            from pydoll.browser.options import ChromiumOptions

            opts = ChromiumOptions()  # type: ignore[no-untyped-call]
            opts.headless = False  # headless fails Cloudflare
            opts.start_timeout = 30  # WSL2 Chrome startup can be slow
            for path in [
                "/usr/bin/google-chrome",
                "/usr/bin/google-chrome-stable",
                "/usr/bin/chromium",
            ]:
                if os.path.exists(path):
                    opts.binary_location = path
                    break

            # Persistent profile so cf_clearance survives between runs
            opts.add_argument(f"--user-data-dir={_profile}")
            opts.add_argument("--disable-blink-features=AutomationControlled")
            # Required on Linux/WSL2 — Chrome sandbox needs kernel namespaces
            opts.add_argument("--no-sandbox")
            opts.add_argument("--disable-dev-shm-usage")
            opts.add_argument("--log-level=3")
            # Prevent Chrome from throttling idle tabs — keeps CDP WebSocket alive
            opts.add_argument("--disable-background-timer-throttling")
            opts.add_argument("--disable-renderer-backgrounding")
            opts.add_argument("--disable-backgrounding-occluded-windows")

            if _EXTENSION_PATH.exists():
                opts.add_argument(f"--load-extension={_EXTENSION_PATH}")
                logger.debug("[%s] Chrome extension loaded successfully", self._name)
            else:
                logger.debug("Chrome extension not found at %s", _EXTENSION_PATH)

            self._browser = Chrome(options=opts)
            self._tab = await self._browser.start()
            self._keepalive_task = asyncio.create_task(self._keepalive_loop())

    async def navigate(self, url: str) -> None:
        """Navigate the browser tab to *url* without waiting for a challenge.

        Intended to be called under a fetch gate so only the network request is
        serialized.  Call wait_for_challenge() afterwards (outside the gate) to
        poll until Cloudflare's JS challenge resolves.

        Raises:
            PageLoadError: If CDP navigation fails.
        """
        await self._ensure_browser()
        tab = self._tab
        try:
            await asyncio.wait_for(tab.go_to(url), timeout=30)
        except TimeoutError as exc:
            raise PageLoadError(
                f"Navigation timed out after 30s for {url}", url=url, cause=exc
            ) from exc
        except KeyError as exc:
            raise PageLoadError(
                f"CDP navigation response missing expected key for {url}: {exc}",
                url=url,
                cause=exc,
            ) from exc
        except (PydollException, OSError, ConnectionError) as exc:
            browser = self._browser
            if browser is not None:
                try:
                    await browser.stop()  # type: ignore[no-untyped-call]
                except Exception as stop_exc:
                    logger.debug(
                        "browser.stop() raised during error cleanup: %s", stop_exc
                    )
            self._browser = None
            self._tab = None
            raise PageLoadError(
                f"Failed to navigate to {url}: {exc}", url=url, cause=exc
            ) from exc

    async def wait_for_challenge(self, url: str) -> str:
        """Poll page_source until the Cloudflare challenge resolves.

        Must be called after navigate().  Runs outside the fetch gate so the
        120-second polling window does not block other workers.

        Returns:
            The HTML source of the fully-loaded destination page.

        Raises:
            PageLoadError: If the challenge does not resolve within the timeout,
                or if the tab is not available.
            RateLimitError: If the resolved page signals rate limiting.
        """
        if self._tab is None:
            raise PageLoadError("No active tab — call navigate() first", url=url)
        content: str = await self._wait_for_challenge(self._tab, url)
        if (
            "too many requests" in content.lower()
            or "rate limit" in content.lower()
        ):
            raise RateLimitError(f"Rate limit detected at {url}", url=url)
        return content

    async def _wait_for_challenge(self, tab: Any, url: str) -> str:
        """Poll page_source until the Cloudflare challenge resolves.

        Cloudflare's JS challenge fires LOAD_EVENT_FIRED on the challenge page,
        not on the final destination. This method polls every second until none
        of the challenge markers appear in the first 1 KB of HTML, then returns
        the resolved page source.

        Args:
            tab: The active pydoll Tab.
            url: Original URL (for error context).

        Returns:
            The HTML source of the fully-loaded destination page.

        Raises:
            PageLoadError: If the challenge does not resolve within the timeout.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + _CHALLENGE_TIMEOUT

        challenge_logged = False
        while loop.time() < deadline:
            try:
                source: str = await asyncio.wait_for(tab.page_source, timeout=10)
            except TimeoutError:
                await asyncio.sleep(1)
                continue
            except KeyError:
                await asyncio.sleep(1)
                continue
            except (OSError, ConnectionError) as exc:
                raise PageLoadError(
                    f"CDP connection lost during challenge poll: {exc}", url=url
                ) from exc
            peek = source[:1024].lower()
            if not any(marker in peek for marker in _CHALLENGE_MARKERS):
                return source
            if not challenge_logged:
                logger.debug(
                    "[%s] Cloudflare challenge detected — waiting up to %ds",
                    self._name,
                    _CHALLENGE_TIMEOUT,
                )
                challenge_logged = True
            await asyncio.sleep(1)

        raise PageLoadError(
            f"Cloudflare challenge did not resolve after {_CHALLENGE_TIMEOUT}s",
            url=url,
        )

    async def execute_script(self, script: str) -> None:
        """Execute *script* in the current page context via CDP Runtime.evaluate."""
        if self._tab is None:
            raise PageLoadError(
                "No active tab — call fetch() or navigate() first", url=""
            )
        try:
            await self._tab.execute_script(script)
        except (PydollException, OSError, ConnectionError) as exc:
            raise PageLoadError(f"execute_script failed: {exc}", url="") from exc

    async def get_page_source(self) -> str:
        """Return the current page's outer HTML without navigating."""
        if self._tab is None:
            raise PageLoadError(
                "No active tab — call fetch() or navigate() first", url=""
            )
        try:
            return await asyncio.wait_for(self._tab.page_source, timeout=10)
        except TimeoutError as exc:
            raise PageLoadError("get_page_source timed out after 10s", url="") from exc
        except (PydollException, OSError, ConnectionError) as exc:
            raise PageLoadError(f"get_page_source failed: {exc}", url="") from exc

    async def fetch(self, url: str) -> str:
        """Navigate to *url* and return the page's outer HTML.

        Lazily creates a Chrome browser on the first call and reuses it on
        subsequent calls. If Cloudflare intercepts the request, waits for the
        JS challenge to resolve before returning content.

        Args:
            url: The URL to fetch.

        Returns:
            The complete HTML source of the loaded page.

        Raises:
            PageLoadError: If navigation fails or Cloudflare challenge times out.
            RateLimitError: If the page signals rate limiting.
        """
        await self._ensure_browser()
        tab = self._tab
        logger.debug("Fetching URL: %s", url)

        try:
            try:
                await tab.go_to(url)
            except KeyError as exc:
                raise PageLoadError(
                    f"CDP navigation response missing expected key for {url}: {exc}",
                    url=url,
                    cause=exc,
                ) from exc
            # pydoll page_source stubs lack Awaitable annotation
            content: str = await self._wait_for_challenge(tab, url)
            if (
                "too many requests" in content.lower()
                or "rate limit" in content.lower()
            ):
                # TODO(phase-5): replace with CDP Network.responseReceived
                # when pydoll event API stabilizes
                raise RateLimitError(f"Rate limit detected at {url}", url=url)
            return content
        except (PageLoadError, RateLimitError):
            raise
        except (PydollException, OSError, ConnectionError) as exc:
            logger.debug("Fetch failed for %s: %s", url, exc)
            browser = self._browser
            if browser is not None:
                try:
                    await browser.stop()  # type: ignore[no-untyped-call]
                except Exception as stop_exc:
                    logger.debug(
                        "browser.stop() raised during error cleanup: %s",
                        stop_exc,
                    )
            self._browser = None
            self._tab = None
            raise PageLoadError(
                f"Failed to fetch {url}: {exc}",
                url=url,
                cause=exc,
            ) from exc

    async def _keepalive_loop(self) -> None:
        """Send a lightweight CDP ping every 30s to keep the WebSocket alive."""
        while True:
            await asyncio.sleep(30)
            if self._tab is None:
                return
            try:
                await asyncio.wait_for(self._tab.page_source, timeout=5)
            except Exception:
                return

    async def close(self) -> None:
        """Stop the browser process and release CDP resources.

        Safe to call even if no fetch() has been performed yet.
        """
        if self._keepalive_task is not None:
            self._keepalive_task.cancel()
            try:
                await self._keepalive_task
            except (asyncio.CancelledError, Exception):
                pass
            self._keepalive_task = None
        if self._browser is not None:
            logger.debug("Stopping Chrome browser")
            await self._browser.stop()  # type: ignore[no-untyped-call]
            self._browser = None
            self._tab = None
            self._xvfb.stop()
