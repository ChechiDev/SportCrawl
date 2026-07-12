"""Remote CDP ScrapingEngine — connects to a pre-running Chromium over WebSocket.

Instead of spawning a local browser process, RemoteCDPEngine connects to an
existing Chromium instance exposed via --remote-debugging-port (e.g. in Docker).

Design contract:
- _ensure_connected() is called lazily on first fetch().
- close() disconnects the WebSocket only — does NOT send Browser.close CDP command
  or kill the remote process. The remote browser is a shared service.
- Each fetch() opens a fresh tab, navigates, and closes it after returning content,
  preventing session state from leaking between requests.
- _wait_for_challenge() polls page_source until Cloudflare challenge resolves.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp
from pydoll.browser.chromium.chrome import Chrome
from pydoll.exceptions import PydollException

from core.exceptions.scraper import PageLoadError, RateLimitError
from ports.browser import ScrapingEngine

logger = logging.getLogger(__name__)

_CHALLENGE_MARKERS = ("just a moment", "checking your browser")
_CHALLENGE_TIMEOUT = 60  # seconds
_CDP_VERSION_PATH = "/json/version"


class RemoteCDPEngine(ScrapingEngine):
    """ScrapingEngine backed by a remote Chromium instance over CDP/WebSocket.

    Connects to a Chromium process launched with --remote-debugging-port
    (e.g. inside a Docker container) instead of spawning a local browser process.

    The remote browser lifecycle is managed externally; close() only releases
    the WebSocket connection, not the remote process.
    """

    def __init__(self, cdp_host: str = "localhost", cdp_port: int = 9222) -> None:
        self._cdp_host = cdp_host
        self._cdp_port = cdp_port
        self._browser: Chrome | None = None
        # pydoll Tab type is not exported; Any justified — see PydollEngine note
        self._tab: Any = None

    async def __aenter__(self) -> RemoteCDPEngine:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def _resolve_ws_url(self) -> str:
        """Fetch the WebSocket debugger URL from the CDP /json/version endpoint."""
        url = f"http://{self._cdp_host}:{self._cdp_port}{_CDP_VERSION_PATH}"
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=timeout) as resp:
                data = await resp.json(content_type=None)
        ws_url: str = data["webSocketDebuggerUrl"]
        logger.debug("Resolved CDP WebSocket URL: %s", ws_url)
        return ws_url

    async def _ensure_connected(self) -> None:
        """Lazily connect to the remote browser on first fetch()."""
        if self._browser is None:
            logger.debug(
                "Connecting to remote Chromium at %s:%d",
                self._cdp_host,
                self._cdp_port,
            )
            ws_url = await self._resolve_ws_url()
            self._browser = Chrome(connection_port=self._cdp_port)
            self._tab = await self._browser.connect(ws_url)
            logger.info("Connected to remote Chromium: %s", ws_url)

    async def _wait_for_challenge(self, tab: Any, url: str) -> str:
        """Poll page_source until the Cloudflare challenge resolves.

        Args:
            tab: The active pydoll Tab.
            url: Original URL (for error context only).

        Returns:
            Resolved HTML source of the destination page.

        Raises:
            PageLoadError: If challenge does not resolve within _CHALLENGE_TIMEOUT.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + _CHALLENGE_TIMEOUT

        while loop.time() < deadline:
            source: str = await tab.page_source
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
        """Navigate to *url* using a fresh remote tab and return the page's HTML.

        Opens a new tab per request to prevent session state from leaking.

        Args:
            url: The URL to fetch.

        Returns:
            The complete HTML source of the loaded page.

        Raises:
            PageLoadError: If navigation fails or Cloudflare challenge times out.
            RateLimitError: If the page signals rate limiting.
        """
        await self._ensure_connected()
        assert self._browser is not None
        logger.debug("Fetching URL via remote CDP: %s", url)

        tab = await self._browser.new_tab()
        try:
            await tab.go_to(url)
            content: str = await self._wait_for_challenge(tab, url)
            if (
                "too many requests" in content.lower()
                or "rate limit" in content.lower()
            ):
                raise RateLimitError(f"Rate limit detected at {url}", url=url)
            return content
        except (PageLoadError, RateLimitError):
            raise
        except PydollException as exc:
            logger.debug("Remote fetch failed for %s: %s", url, exc)
            raise PageLoadError(
                f"Failed to fetch {url} via remote CDP: {exc}",
                url=url,
                cause=exc,
            ) from exc
        finally:
            try:
                await tab.close()  # type: ignore[no-untyped-call]
            except PydollException:
                logger.debug("Tab close raised during cleanup; ignoring")

    async def close(self) -> None:
        """Disconnect the WebSocket without killing the remote browser process.

        Safe to call even if no fetch() has been performed.
        """
        if self._browser is not None:
            logger.debug("Disconnecting from remote Chromium")
            # browser.close() = WebSocket disconnect only; browser.stop() would kill
            # the remote process — never call stop() on a shared remote browser.
            await self._browser.close()  # type: ignore[no-untyped-call]
            self._browser = None
            self._tab = None
