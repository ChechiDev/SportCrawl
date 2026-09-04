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
from pathlib import Path
from typing import Any

from pydoll.browser.chromium.chrome import Chrome
from pydoll.exceptions import PydollException

from core.exceptions.scraper import PageLoadError, RateLimitError, WarmupError
from infrastructure.browser.xvfb_display import XvfbDisplay
from ports.browser import ScriptableEngine

logger = logging.getLogger(__name__)


_CHALLENGE_MARKERS = ("just a moment", "checking your browser")

# Maximum seconds to wait for a single CDP command during storage injection.
# Chosen to exceed realistic CDP round-trip latency (< 1 s) while keeping the
# browser-start gate bounded when the pipe is unresponsive.
_INJECT_STORAGE_TIMEOUT_S: float = 15.0
_EXTENSION_PATH = Path(__file__).parents[2] / "extensions" / "sportcrawl-chrome"
_CHALLENGE_TIMEOUT = 120  # seconds — Turnstile managed challenge can take 30–90s


class PydollEngine(ScriptableEngine):
    """ScrapingEngine that drives Chrome via CDP using pydoll-python.

    The browser is started lazily on the first fetch() call and must be
    explicitly released via close(), or used as an async context manager.
    """

    def __init__(
        self,
        profile_dir: str | None = None,
        name: str = "engine",
        display: XvfbDisplay | None = None,
    ) -> None:
        self._browser: Chrome | None = None
        # pydoll Tab type is not exported; using Any until upstream types stabilize
        self._tab: Any = None
        if display is not None:
            self._display: XvfbDisplay = display
            self._display_owned: bool = False
        else:
            self._display = XvfbDisplay()
            self._display_owned = True
        self._profile_dir: str = profile_dir or "/tmp/sportcrawl-chrome-profile"
        self._name = name
        self._keepalive_task: asyncio.Task[None] | None = None
        self._start_lock: asyncio.Lock = asyncio.Lock()

    async def __aenter__(self) -> PydollEngine:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def start(self) -> None:
        """Explicitly start the Chrome browser. Idempotent."""
        await self._ensure_browser()

    async def warmup(self, readiness_url: str) -> None:
        """Navigate to readiness_url and verify the browser can reach the destination.

        Handles Cloudflare challenge flow if the readiness URL triggers one.
        Readiness is proven by a non-empty HTML response from the resolved page —
        not by cookie presence.

        Args:
            readiness_url: URL to navigate to for readiness verification.

        Raises:
            WarmupError: If navigation fails, the challenge does not resolve,
                or the response is empty.
        """
        await self.start()
        try:
            await self.navigate(readiness_url)
        except PageLoadError as exc:
            raise WarmupError(
                f"Browser warmup navigation failed for {readiness_url}",
                url=readiness_url,
                cause=exc,
            ) from exc
        try:
            html = await self._wait_for_challenge(self._tab, readiness_url)
        except PageLoadError as exc:
            raise WarmupError(
                f"Browser warmup challenge did not resolve for {readiness_url}",
                url=readiness_url,
                cause=exc,
            ) from exc
        if not html or not html.strip():
            raise WarmupError(
                f"Browser warmup: empty response from {readiness_url}",
                url=readiness_url,
            )
        logger.info(
            "[%s] Browser warmed up successfully at %s", self._name, readiness_url
        )

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
        if self._browser is not None:
            return
        async with self._start_lock:
            if self._browser is not None:
                return
            logger.debug("Starting Chrome browser (lazy init)")
            await asyncio.to_thread(self._display.start)

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
        if "too many requests" in content.lower() or "rate limit" in content.lower():
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

    async def inject_storage_config(self, config: dict[str, object]) -> None:
        """Inject *config* into chrome.storage.local via CDP Runtime.callFunctionOn.

        The config dict is passed as a structured CDP argument — no values are
        serialized into the JavaScript function body string, so bearer tokens and
        other secret values never appear in any script string that could be logged.

        Do NOT use dataclasses.asdict() to build *config* — it bypasses any custom
        __repr__ redaction. Build the dict explicitly from non-secret and secret
        fields with awareness of which values are sensitive.
        """
        from pydoll.commands.runtime_commands import RuntimeCommands

        if self._tab is None:
            raise PageLoadError(
                "No active tab — call start() before inject_storage_config()", url=""
            )
        cmd = RuntimeCommands.call_function_on(
            function_declaration=(
                "function(cfg) {"
                " return new Promise(function(resolve) {"
                " chrome.storage.local.set(cfg, function() { resolve(true); });"
                " });"
                "}"
            ),
            arguments=[{"value": config}],
            await_promise=True,
            return_by_value=True,
        )
        try:
            await asyncio.wait_for(
                self._tab._execute_command(cmd),
                timeout=_INJECT_STORAGE_TIMEOUT_S,
            )
        except (
            TimeoutError,
            PydollException,
            OSError,
            ConnectionError,
            AttributeError,
        ) as exc:
            raise PageLoadError(
                "inject_storage_config failed", url=""
            ) from exc

    async def inject_storage_config_to_extension(
        self, config: dict[str, object]
    ) -> None:
        """Inject config into chrome.storage.local via the extension SW context.

        Uses Target.getTargets → Target.attachToTarget → Runtime.callFunctionOn
        on the SW session, NOT on the main tab. Config values are passed as
        structured CDP arguments — never serialized into the JS function body.
        """
        if self._tab is None:
            raise PageLoadError(
                "No active tab — call start() before"
                " inject_storage_config_to_extension()",
                url="",
            )
        try:
            # Step 1: find the extension service worker target
            get_targets_cmd: dict[str, Any] = {
                "method": "Target.getTargets",
                "params": {},
            }
            targets_result = await asyncio.wait_for(
                self._tab._execute_command(get_targets_cmd),
                timeout=_INJECT_STORAGE_TIMEOUT_S,
            )
            target_infos = targets_result.get("result", {}).get("targetInfos", [])
            sw_target = next(
                (
                    t
                    for t in target_infos
                    if t.get("type") == "service_worker"
                    and t.get("url", "").startswith("chrome-extension://")
                ),
                None,
            )
            if sw_target is None:
                raise PageLoadError(
                    "inject_storage_config_to_extension:"
                    " no extension service-worker target found",
                    url="",
                )

            # Step 2: attach to SW target
            target_id: str = sw_target["targetId"]
            attach_cmd: dict[str, Any] = {
                "method": "Target.attachToTarget",
                "params": {"targetId": target_id, "flatten": True},
            }
            attach_result = await asyncio.wait_for(
                self._tab._execute_command(attach_cmd),
                timeout=_INJECT_STORAGE_TIMEOUT_S,
            )
            session_id: str = attach_result.get("result", {}).get("sessionId", "")

            # Step 3: get global object in SW context
            eval_cmd: dict[str, Any] = {
                "method": "Runtime.evaluate",
                "params": {"expression": "this", "returnByValue": False},
                "sessionId": session_id,
            }
            eval_result = await asyncio.wait_for(
                self._tab._execute_command(eval_cmd),
                timeout=_INJECT_STORAGE_TIMEOUT_S,
            )
            object_id: str = (
                eval_result.get("result", {}).get("result", {}).get("objectId", "")
            )

            # Step 4: call function on SW global — config as structured arg, not in body
            _fn = "function(cfg) { chrome.storage.local.set(cfg); }"
            call_cmd: dict[str, Any] = {
                "method": "Runtime.callFunctionOn",
                "params": {
                    "functionDeclaration": _fn,
                    "objectId": object_id,
                    "arguments": [{"value": config}],
                },
                "sessionId": session_id,
            }
            await asyncio.wait_for(
                self._tab._execute_command(call_cmd),
                timeout=_INJECT_STORAGE_TIMEOUT_S,
            )
        except PageLoadError:
            raise
        except (
            TimeoutError,
            PydollException,
            OSError,
            ConnectionError,
            AttributeError,
            KeyError,
        ) as exc:
            raise PageLoadError(
                "inject_storage_config_to_extension failed", url=""
            ) from exc

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
                await asyncio.wait_for(tab.go_to(url), timeout=30)
            except TimeoutError as exc:
                raise PageLoadError("Navigation timeout", url=url, cause=exc) from exc
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
                await asyncio.wait_for(
                    self._tab.execute_script("1"),
                    timeout=5,
                )
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
            try:
                await asyncio.wait_for(
                    self._browser.stop(), timeout=10  # type: ignore[no-untyped-call]
                )
            except (TimeoutError, Exception):
                pass
            self._browser = None
            self._tab = None
        if self._display_owned:
            self._display.stop()
