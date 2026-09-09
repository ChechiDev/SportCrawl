# cli/real_clearance_composition.py
"""Factory functions for real-clearance seam callables.

Extracted from cli/main.py smoke_clearance --real-clearance path so that
composition logic is testable in isolation and cli/main.py stays thin.

All factories accept an explicit event loop so browser and injector/navigator
share the same loop throughout the session — pydoll's async objects bind to
the loop on creation; using separate loops raises RuntimeError.
"""
from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse as _urlparse

from dotenv import dotenv_values

from core.exceptions.scraper import PageLoadError

_NAV_TIMEOUT_S: float = 30.0
_INJECT_TIMEOUT_S: float = 15.0
_CLEANUP_TIMEOUT_S: float = 5.0
_STOP_TIMEOUT_S: float = 3.0


def make_extension_config_injector(
    engine: Any,
    config: dict[str, Any],
    loop: asyncio.AbstractEventLoop | None = None,
) -> Callable[[], Any]:
    """Return a sync callable that injects extension config via CDP.

    Config values are passed as a structured dict — no values are serialised
    into the JavaScript function body string. The bearer token therefore never
    appears in any script string that could be logged by pydoll or a future
    debug wrapper.

    Runs on the provided event loop so all pydoll async objects remain on one
    loop throughout the session.
    """

    async def _inject_with_timeout() -> None:
        _pydoll_logger = logging.getLogger("pydoll")
        _orig_level = _pydoll_logger.level
        _pydoll_logger.setLevel(logging.WARNING)
        try:
            try:
                await asyncio.wait_for(
                    engine.inject_storage_config(config),
                    timeout=_INJECT_TIMEOUT_S,
                )
            except TimeoutError:
                try:
                    await asyncio.wait_for(engine.stop(), timeout=_STOP_TIMEOUT_S)
                except Exception:  # noqa: BLE001
                    pass
                raise RuntimeError(
                    "extension config injection failed — timed out"
                ) from None
        finally:
            _pydoll_logger.setLevel(_orig_level)

    if loop is None:
        return _inject_with_timeout

    def _extension_config_injector() -> None:
        _is_closed = loop.is_closed()
        _is_running = loop.is_running()
        if _is_closed or _is_running:
            raise RuntimeError(
                "extension config loop is not usable "
                f"(closed={_is_closed}, running={_is_running})"
            )
        loop.run_until_complete(_inject_with_timeout())

    return _extension_config_injector


def make_cleanup(loop: asyncio.AbstractEventLoop) -> Callable[[], None]:
    """Return a sync callable that cancels pending tasks and closes the event loop.

    Safe to call multiple times — subsequent calls are no-ops. All exceptions
    are swallowed so cleanup never prevents the process from exiting cleanly.
    """

    def _cleanup() -> None:
        try:
            if loop.is_closed():
                return
            pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(
                    asyncio.wait_for(
                        asyncio.gather(*pending, return_exceptions=True),
                        timeout=_CLEANUP_TIMEOUT_S,
                    )
                )
        except Exception:  # noqa: BLE001
            logging.getLogger(__name__).debug(
                "cleanup error during loop teardown", exc_info=True
            )
        finally:
            if not loop.is_closed():
                loop.close()

    return _cleanup


def make_target_navigator(
    engine: Any,
    loop: asyncio.AbstractEventLoop | None = None,
) -> Callable[[], Any]:
    """Return a sync callable that navigates to the configured clearance target.

    The target URL is read generically from the environment (SCRAPING__TARGET_URL)
    — no domain is hardcoded here. Navigation failure raises PageLoadError, which
    the harness maps to BLOCKED at the target_navigation gate.

    Runs on the provided event loop so all pydoll async objects remain on one
    loop throughout the session.
    """

    def _resolve_nav_url() -> str:
        _env_overlay = {**dotenv_values(".env"), **os.environ}
        _nav_url = (_env_overlay.get("SCRAPING__TARGET_URL") or "").strip()
        if not _nav_url:
            raise RuntimeError(
                "SCRAPING__TARGET_URL is not set — "
                "cannot navigate to clearance target"
            )
        # Reject scheme-less URLs (e.g. //example.com) — urlparse gives
        # an empty scheme for these.
        _parsed = _urlparse(_nav_url)
        if not _parsed.scheme:
            raise RuntimeError("target navigation failed — invalid URL scheme")
        return _nav_url

    async def _navigate_with_timeout() -> None:
        _nav_url = _resolve_nav_url()
        try:
            await asyncio.wait_for(engine.navigate(_nav_url), timeout=_NAV_TIMEOUT_S)
        except TimeoutError:
            try:
                await asyncio.wait_for(engine.stop(), timeout=_STOP_TIMEOUT_S)
            except Exception:  # noqa: BLE001
                pass
            raise RuntimeError("target navigation failed — timed out") from None
        except PageLoadError as _nav_exc:
            raise PageLoadError("target navigation failed") from _nav_exc

    if loop is None:
        return _navigate_with_timeout

    def _target_navigator() -> None:
        _is_closed = loop.is_closed()
        _is_running = loop.is_running()
        if _is_closed or _is_running:
            raise RuntimeError(
                "target navigation loop is not usable "
                f"(closed={_is_closed}, running={_is_running})"
            )
        loop.run_until_complete(_navigate_with_timeout())

    return _target_navigator
