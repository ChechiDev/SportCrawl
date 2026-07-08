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
"""

from __future__ import annotations

import logging
from typing import Any

from pydoll.browser.chromium.chrome import Chrome
from pydoll.exceptions import PydollException

from core.exceptions.scraper import PageLoadError
from infrastructure.browser.engine import ScrapingEngine

logger = logging.getLogger(__name__)


class PydollEngine(ScrapingEngine):
    """ScrapingEngine that drives Chrome via CDP using pydoll-python.

    The browser is started lazily on the first fetch() call and must be
    explicitly released via close(), or used as an async context manager.
    """

    def __init__(self) -> None:
        self._browser: Chrome | None = None
        # pydoll Tab type is not exported; using Any until upstream types stabilize
        self._tab: Any = None

    async def __aenter__(self) -> PydollEngine:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def _ensure_browser(self) -> None:
        """Lazily initialize the Chrome browser and its initial tab."""
        if self._browser is None:
            logger.debug("Starting Chrome browser (lazy init)")
            self._browser = Chrome()
            self._tab = await self._browser.start()

    async def fetch(self, url: str) -> str:
        """Navigate to *url* and return the page's outer HTML.

        Lazily creates a Chrome browser on the first call and reuses it on
        subsequent calls.

        Args:
            url: The URL to fetch.

        Returns:
            The complete HTML source of the loaded page.

        Raises:
            PageLoadError: If navigation fails for any pydoll-side reason
                (DNS failure, page load timeout, connection error, etc.).
        """
        await self._ensure_browser()
        tab = self._tab
        logger.debug("Fetching URL: %s", url)

        try:
            await tab.go_to(url)
            return await tab.page_source  # type: ignore[no-any-return]  # pydoll page_source stubs lack Awaitable annotation
        except PydollException as exc:
            logger.debug("Fetch failed for %s: %s", url, exc)
            try:
                await self._browser.stop()  # type: ignore[union-attr]
            except Exception:
                logger.debug("browser.stop() raised during error cleanup; ignoring")
            finally:
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
