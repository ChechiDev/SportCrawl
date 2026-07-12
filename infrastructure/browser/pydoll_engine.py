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
from ports.browser import ScrapingEngine

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
            logger.warning(
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
_CHALLENGE_TIMEOUT = 60  # seconds — Turnstile managed challenge can take 30–45s


class PydollEngine(ScrapingEngine):
    """ScrapingEngine that drives Chrome via CDP using pydoll-python.

    The browser is started lazily on the first fetch() call and must be
    explicitly released via close(), or used as an async context manager.
    """

    def __init__(self) -> None:
        self._browser: Chrome | None = None
        # pydoll Tab type is not exported; using Any until upstream types stabilize
        self._tab: Any = None
        self._xvfb: _XvfbManager = _XvfbManager()

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

            _profile = "/tmp/sportcrawl-chrome-profile"
            self._clear_profile_lock(_profile)

            from pydoll.browser.options import ChromiumOptions

            opts = ChromiumOptions()  # type: ignore[no-untyped-call]
            opts.headless = False  # headless fails Cloudflare
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

            if _EXTENSION_PATH.exists():
                opts.add_argument(f"--load-extension={_EXTENSION_PATH}")
                logger.info("Chrome extension loaded: %s", _EXTENSION_PATH)
            else:
                logger.warning("Chrome extension not found at %s", _EXTENSION_PATH)

            self._browser = Chrome(options=opts)
            self._tab = await self._browser.start()

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

        while loop.time() < deadline:
            try:
                source: str = await tab.page_source
            except KeyError:
                # CDP Runtime.evaluate response missing 'value' — tab still
                # in a transitional state (e.g. large page still loading).
                await asyncio.sleep(1)
                continue
            peek = source[:1024].lower()
            if not any(marker in peek for marker in _CHALLENGE_MARKERS):
                return source
            remaining = int(deadline - loop.time())
            logger.info("Cloudflare challenge active — waiting (%ds left)", remaining)
            await asyncio.sleep(1)

        raise PageLoadError(
            f"Cloudflare challenge did not resolve after {_CHALLENGE_TIMEOUT}s",
            url=url,
        )

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
            await tab.go_to(url)
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
        except PydollException as exc:
            logger.debug("Fetch failed for %s: %s", url, exc)
            browser = self._browser
            if browser is not None:
                try:
                    await browser.stop()  # type: ignore[no-untyped-call]
                except PydollException:
                    logger.debug("browser.stop() raised during error cleanup; ignoring")
            self._browser = None
            self._tab = None
            raise PageLoadError(
                f"Failed to fetch {url}: {exc}",
                url=url,
                cause=exc,
            ) from exc

    async def close(self) -> None:
        """Stop the browser process and release CDP resources.

        Safe to call even if no fetch() has been performed yet.
        """
        if self._browser is not None:
            logger.debug("Stopping Chrome browser")
            await self._browser.stop()  # type: ignore[no-untyped-call]
            self._browser = None
            self._tab = None
            self._xvfb.stop()
