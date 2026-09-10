"""Tests for cli/real_clearance_composition.py — structural and behavioral."""
from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import cli.real_clearance_composition as _comp_module
from core.exceptions.scraper import PageLoadError

# ---------------------------------------------------------------------------
# Behavioral — composition module attributes (replaces structural file-path tests)
# ---------------------------------------------------------------------------


def test_composition_module_exposes_expected_names() -> None:
    """Module must expose make_extension_config_injector, make_target_navigator,
    and make_cleanup — the three public factory functions."""
    import cli.real_clearance_composition as mod  # type: ignore[import]

    assert hasattr(mod, "make_extension_config_injector"), (
        "cli.real_clearance_composition must expose make_extension_config_injector"
    )
    assert hasattr(mod, "make_target_navigator"), (
        "cli.real_clearance_composition must expose make_target_navigator"
    )
    assert hasattr(mod, "make_cleanup"), (
        "cli.real_clearance_composition must expose make_cleanup"
    )


# ---------------------------------------------------------------------------
# Behavioral — main.py must NOT define these closures inline
# (regression guard: source scan is the only way to verify delegation)
# ---------------------------------------------------------------------------


def test_main_does_not_define_injector_closure_inline() -> None:
    """cli/main.py must not inline _extension_config_injector.

    This test is intentionally structural because no behavioral test can prove
    that a name is *absent* from a module's source without reading the source.
    """
    import inspect

    import cli.main as _mod

    src = inspect.getsource(_mod)
    assert "def _extension_config_injector" not in src, (
        "cli/main.py must not define _extension_config_injector inline — "
        "it must be a factory in cli.real_clearance_composition"
    )


def test_main_does_not_define_navigator_closure_inline() -> None:
    """cli/main.py must not inline _target_navigator.

    Same rationale as test_main_does_not_define_injector_closure_inline.
    """
    import inspect

    import cli.main as _mod

    src = inspect.getsource(_mod)
    assert "def _target_navigator" not in src, (
        "cli/main.py must not define _target_navigator inline — "
        "it must be a factory in cli.real_clearance_composition"
    )


# ---------------------------------------------------------------------------
# Behavioral — make_extension_config_injector
# ---------------------------------------------------------------------------


def test_make_injector_calls_engine_inject() -> None:
    from cli.real_clearance_composition import make_extension_config_injector

    loop = asyncio.new_event_loop()
    engine = MagicMock()
    engine.inject_storage_config_to_extension = AsyncMock()

    config = {
        "work_server_url": "http://127.0.0.1:9731",
        "work_server_token": "tok",
        "profile_id": "smoke",
        "worker_id": "smoke",
        "disable_task_polling": True,
    }

    _url_patch = {"SCRAPING__TARGET_URL": "https://example.com"}
    with (
        patch("cli.real_clearance_composition.dotenv_values", return_value={}),
        patch.dict(os.environ, _url_patch, clear=False),
    ):
        injector = make_extension_config_injector(
            engine=engine, config=config, loop=loop
        )
        try:
            injector()
        finally:
            loop.close()

    call_config = engine.inject_storage_config_to_extension.call_args[0][0]
    # All original keys must be preserved
    for key, value in config.items():
        assert call_config[key] == value, (
            f"Key {key!r} must be preserved in call config"
        )
    # allowed_clearance_domain must be added
    assert call_config["allowed_clearance_domain"] == "example.com"


def test_make_injector_calls_engine_inject_with_empty_config() -> None:
    """Calling the injector with an empty config dict must still invoke the engine."""
    from cli.real_clearance_composition import make_extension_config_injector

    loop = asyncio.new_event_loop()
    engine = MagicMock()
    engine.inject_storage_config_to_extension = AsyncMock()

    _url_patch = {"SCRAPING__TARGET_URL": "https://example.com"}
    with (
        patch("cli.real_clearance_composition.dotenv_values", return_value={}),
        patch.dict(os.environ, _url_patch, clear=False),
    ):
        injector = make_extension_config_injector(
            engine=engine, config={}, loop=loop
        )
        try:
            injector()
        finally:
            loop.close()

    engine.inject_storage_config_to_extension.assert_called_once()
    call_config = engine.inject_storage_config_to_extension.call_args[0][0]
    assert call_config.get("allowed_clearance_domain") == "example.com"


def test_make_injector_raises_when_loop_closed() -> None:
    from cli.real_clearance_composition import make_extension_config_injector

    loop = asyncio.new_event_loop()
    loop.close()

    engine = MagicMock()
    _url_env = {"SCRAPING__TARGET_URL": "https://example.com"}
    with (
        patch("cli.real_clearance_composition.dotenv_values", return_value={}),
        patch.dict(os.environ, _url_env, clear=False),
    ):
        injector = make_extension_config_injector(engine=engine, config={}, loop=loop)

    with pytest.raises(RuntimeError, match="not usable"):
        injector()


def test_make_injector_raises_when_loop_running() -> None:
    """Injector must refuse to run when the loop is already running."""
    from cli.real_clearance_composition import make_extension_config_injector

    async def _inner() -> None:
        loop = asyncio.get_event_loop()
        engine = MagicMock()
        _url_env = {"SCRAPING__TARGET_URL": "https://example.com"}
        with (
            patch("cli.real_clearance_composition.dotenv_values", return_value={}),
            patch.dict(os.environ, _url_env, clear=False),
        ):
            injector = make_extension_config_injector(
                engine=engine, config={}, loop=loop
            )
        with pytest.raises(RuntimeError, match="not usable"):
            injector()

    asyncio.run(_inner())


# ---------------------------------------------------------------------------
# Behavioral — make_target_navigator
# ---------------------------------------------------------------------------


def test_make_navigator_raises_on_missing_url() -> None:
    from cli.real_clearance_composition import make_target_navigator

    loop = asyncio.new_event_loop()
    engine = MagicMock()
    engine.navigate = AsyncMock()

    # D4: URL resolved at construction time — patch must wrap the factory call
    with patch("cli.real_clearance_composition.dotenv_values", return_value={}), \
         patch.dict("os.environ", {}, clear=True):
        with pytest.raises(RuntimeError, match="SCRAPING__TARGET_URL"):
            make_target_navigator(engine=engine, loop=loop)

    loop.close()


def test_make_navigator_raises_on_scheme_less_url() -> None:
    from cli.real_clearance_composition import make_target_navigator

    loop = asyncio.new_event_loop()
    engine = MagicMock()
    engine.navigate = AsyncMock()

    # D4: URL resolved at construction time — patch must wrap the factory call
    with patch("cli.real_clearance_composition.dotenv_values", return_value={}), \
         patch.dict("os.environ", {"SCRAPING__TARGET_URL": "//example.com"}):
        with pytest.raises(RuntimeError, match="target navigation"):
            make_target_navigator(engine=engine, loop=loop)

    loop.close()


def test_make_navigator_calls_engine_navigate() -> None:
    from cli.real_clearance_composition import make_target_navigator

    loop = asyncio.new_event_loop()
    engine = MagicMock()
    engine.navigate = AsyncMock()

    # D4: URL resolved at construction time — patch must wrap the factory call
    with patch("cli.real_clearance_composition.dotenv_values", return_value={}), \
         patch.dict("os.environ", {"SCRAPING__TARGET_URL": "https://example.com"}):
        navigator = make_target_navigator(engine=engine, loop=loop)
        navigator()

    engine.navigate.assert_called_once_with("https://example.com")
    loop.close()


def test_navigator_sanitizes_page_load_error_message() -> None:
    """PageLoadError raised by engine.navigate must be re-raised without the raw URL."""
    from cli.real_clearance_composition import make_target_navigator

    loop = asyncio.new_event_loop()
    engine = MagicMock()
    engine.navigate = AsyncMock(
        side_effect=PageLoadError("https://secret.example.com navigation failed")
    )

    # D4: URL resolved at construction time — patch must wrap the factory call
    with patch("cli.real_clearance_composition.dotenv_values", return_value={}), \
         patch.dict(
             "os.environ", {"SCRAPING__TARGET_URL": "https://secret.example.com"}
         ):
        navigator = make_target_navigator(engine=engine, loop=loop)
        with pytest.raises(PageLoadError) as exc_info:
            navigator()

    loop.close()

    assert "https://secret.example.com" not in str(exc_info.value), (
        "PageLoadError message must not contain the raw URL"
    )
    assert "target navigation failed" in str(exc_info.value), (
        "PageLoadError message must contain generic sanitized message"
    )


# ---------------------------------------------------------------------------
# Behavioral — make_cleanup
# ---------------------------------------------------------------------------


def test_make_cleanup_cancels_pending_tasks() -> None:
    """Cleanup must cancel any tasks that are still pending on the loop."""
    from cli.real_clearance_composition import make_cleanup

    loop = asyncio.new_event_loop()

    async def _never_done() -> None:
        await asyncio.sleep(9999)

    async def _schedule() -> asyncio.Task[None]:
        return asyncio.ensure_future(_never_done())

    task = loop.run_until_complete(_schedule())

    cleanup = make_cleanup(loop)
    cleanup()

    assert task.cancelled(), "Pending task must be cancelled by cleanup"


def test_make_cleanup_closes_loop() -> None:
    """Cleanup must close the event loop."""
    from cli.real_clearance_composition import make_cleanup

    loop = asyncio.new_event_loop()
    cleanup = make_cleanup(loop)
    cleanup()

    assert loop.is_closed(), "Event loop must be closed after cleanup"


def test_make_cleanup_is_safe_on_already_closed_loop() -> None:
    """Calling cleanup twice must not raise."""
    from cli.real_clearance_composition import make_cleanup

    loop = asyncio.new_event_loop()
    cleanup = make_cleanup(loop)
    cleanup()
    cleanup()  # second call must be silent


def test_make_navigator_raises_when_loop_closed() -> None:
    """make_target_navigator must raise RuntimeError when called with a closed loop."""
    from unittest.mock import MagicMock

    from cli.real_clearance_composition import make_target_navigator

    loop = asyncio.new_event_loop()
    loop.close()
    engine = MagicMock()

    # D4: URL resolved at construction time — patch must wrap the factory call
    with patch("cli.real_clearance_composition.dotenv_values", return_value={}), \
         patch.dict("os.environ", {"SCRAPING__TARGET_URL": "https://example.com"}):
        nav = make_target_navigator(engine=engine, loop=loop)

    with pytest.raises(RuntimeError, match="loop is not usable"):
        nav()


def test_make_injector_restores_logger_level_on_failure() -> None:
    """make_extension_config_injector must restore pydoll logger level on failure."""
    import logging
    from unittest.mock import AsyncMock, MagicMock

    from cli.real_clearance_composition import make_extension_config_injector

    engine = MagicMock()
    engine.inject_storage_config_to_extension = AsyncMock(
        side_effect=RuntimeError("inject failed")
    )

    logger = logging.getLogger("pydoll")
    orig_level = logger.level

    loop = asyncio.new_event_loop()
    _url_env = {"SCRAPING__TARGET_URL": "https://example.com"}
    with (
        patch("cli.real_clearance_composition.dotenv_values", return_value={}),
        patch.dict(os.environ, _url_env, clear=False),
    ):
        injector = make_extension_config_injector(
            engine=engine, config={"key": "value"}, loop=loop
        )
    try:
        with pytest.raises(RuntimeError, match="inject failed"):
            injector()
    finally:
        loop.close()

    assert logger.level == orig_level, (
        f"pydoll logger level must be restored after failure: "
        f"expected {orig_level}, got {logger.level}"
    )


def test_make_navigator_times_out_on_hung_navigation() -> None:
    """Navigation that never completes raises RuntimeError, not a hang."""
    from cli.real_clearance_composition import make_target_navigator

    async def _hang(_url: str) -> None:
        await asyncio.sleep(9999)

    engine = MagicMock()
    engine.navigate = _hang
    with patch.object(_comp_module, "_NAV_TIMEOUT_S", 0.05), \
         patch("cli.real_clearance_composition.dotenv_values", return_value={}), \
         patch.dict("os.environ", {"SCRAPING__TARGET_URL": "https://example.com"}):
        nav = make_target_navigator(engine)
        loop = asyncio.new_event_loop()
        try:
            with pytest.raises(RuntimeError, match="timed out"):
                loop.run_until_complete(nav())
        finally:
            loop.close()


def test_make_injector_times_out_on_hung_injection() -> None:
    """Injection that never completes raises RuntimeError, not a hang."""
    from cli.real_clearance_composition import make_extension_config_injector

    async def _hang(_cfg: dict) -> None:
        await asyncio.sleep(9999)

    engine = MagicMock()
    engine.inject_storage_config_to_extension = _hang
    _url_env = {"SCRAPING__TARGET_URL": "https://example.com"}
    with (
        patch.object(_comp_module, "_INJECT_TIMEOUT_S", 0.05),
        patch("cli.real_clearance_composition.dotenv_values", return_value={}),
        patch.dict(os.environ, _url_env, clear=False),
    ):
        injector = make_extension_config_injector(engine, {"k": "v"})
        loop = asyncio.new_event_loop()
        try:
            with pytest.raises(RuntimeError, match="timed out"):
                loop.run_until_complete(injector())
        finally:
            loop.close()


def test_cleanup_timeout_uses_named_constant() -> None:
    """Cleanup timeout constant is named, not a magic number."""
    import cli.real_clearance_composition as comp
    assert hasattr(comp, "_CLEANUP_TIMEOUT_S"), "_CLEANUP_TIMEOUT_S must be defined"
    assert isinstance(comp._CLEANUP_TIMEOUT_S, float)


def test_make_navigator_env_overrides_dotenv() -> None:
    """os.environ values take precedence over .env file values."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from cli.real_clearance_composition import make_target_navigator

    engine = MagicMock()
    engine.navigate = AsyncMock()

    loop = asyncio.new_event_loop()

    # D4: URL resolved at construction time — both patches must wrap the factory call
    try:
        with (
            patch(
                "cli.real_clearance_composition.dotenv_values",
                return_value={"SCRAPING__TARGET_URL": "https://dotenv.example.com"},
            ),
            patch.dict(
                "os.environ",
                {"SCRAPING__TARGET_URL": "https://from-env.example.com"},
                clear=False,
            ),
        ):
            navigator = make_target_navigator(engine=engine, loop=loop)
            navigator()
    finally:
        loop.close()

    engine.navigate.assert_called_once_with("https://from-env.example.com")


# ---------------------------------------------------------------------------
# Behavioral — engine.stop() called on timeout (Finding 2)
# ---------------------------------------------------------------------------


def test_navigator_timeout_calls_engine_stop() -> None:
    """On navigation timeout, engine.stop() is called to abort in-flight CDP."""
    from cli.real_clearance_composition import make_target_navigator

    async def _hang(_url: str) -> None:
        await asyncio.sleep(9999)

    engine = MagicMock()
    engine.navigate = _hang
    engine.stop = AsyncMock()
    with patch.object(_comp_module, "_NAV_TIMEOUT_S", 0.05), \
         patch("cli.real_clearance_composition.dotenv_values", return_value={}), \
         patch.dict("os.environ", {"SCRAPING__TARGET_URL": "https://example.com"}):
        nav = make_target_navigator(engine)
        loop = asyncio.new_event_loop()
        try:
            with pytest.raises(RuntimeError, match="timed out"):
                loop.run_until_complete(nav())
        finally:
            loop.close()
    engine.stop.assert_called_once()


def test_injector_timeout_calls_engine_stop() -> None:
    """On injection timeout, engine.stop() is called to abort in-flight CDP."""
    from cli.real_clearance_composition import make_extension_config_injector

    async def _hang(_cfg: dict) -> None:
        await asyncio.sleep(9999)

    engine = MagicMock()
    engine.inject_storage_config_to_extension = _hang
    engine.stop = AsyncMock()
    _url_env = {"SCRAPING__TARGET_URL": "https://example.com"}
    with (
        patch.object(_comp_module, "_INJECT_TIMEOUT_S", 0.05),
        patch("cli.real_clearance_composition.dotenv_values", return_value={}),
        patch.dict(os.environ, _url_env, clear=False),
    ):
        injector = make_extension_config_injector(engine, {"k": "v"})
        loop = asyncio.new_event_loop()
        try:
            with pytest.raises(RuntimeError, match="timed out"):
                loop.run_until_complete(injector())
        finally:
            loop.close()
    engine.stop.assert_called_once()


def test_navigator_timeout_contains_stop_error() -> None:
    """If engine.stop() itself raises, the timeout RuntimeError is still raised."""
    from cli.real_clearance_composition import make_target_navigator

    async def _hang(_url: str) -> None:
        await asyncio.sleep(9999)

    engine = MagicMock()
    engine.navigate = _hang
    engine.stop = AsyncMock(side_effect=RuntimeError("stop failed"))
    with patch.object(_comp_module, "_NAV_TIMEOUT_S", 0.05), \
         patch("cli.real_clearance_composition.dotenv_values", return_value={}), \
         patch.dict("os.environ", {"SCRAPING__TARGET_URL": "https://example.com"}):
        nav = make_target_navigator(engine)
        loop = asyncio.new_event_loop()
        try:
            with pytest.raises(RuntimeError, match="timed out"):
                loop.run_until_complete(nav())
        finally:
            loop.close()


# ---------------------------------------------------------------------------
# D4: early resolution — construction-time failure
# ---------------------------------------------------------------------------


def test_make_navigator_raises_at_construction_if_url_missing() -> None:
    from cli.real_clearance_composition import make_target_navigator

    engine = AsyncMock(spec=["inject_storage_config", "navigate", "stop"])
    with patch.dict(os.environ, {}, clear=True):
        with patch("cli.real_clearance_composition.dotenv_values", return_value={}):
            with pytest.raises(RuntimeError, match="target"):
                make_target_navigator(engine)


# ---------------------------------------------------------------------------
# D5: no chained cause
# ---------------------------------------------------------------------------


def test_navigator_page_load_error_has_no_chained_cause() -> None:
    """PageLoadError.__cause__ must be None — no chained trace can expose raw URLs."""
    from cli.real_clearance_composition import make_target_navigator

    engine = AsyncMock(spec=["inject_storage_config", "navigate", "stop"])
    engine.navigate.side_effect = PageLoadError("internal engine error")
    target_url = "https://sport.example.com"
    _patch = "cli.real_clearance_composition._resolve_nav_url"
    with patch(_patch, return_value=target_url):
        navigator = make_target_navigator(engine)
    loop = asyncio.new_event_loop()
    try:
        with pytest.raises(PageLoadError) as exc_info:
            loop.run_until_complete(navigator())
    finally:
        loop.close()
    err = exc_info.value
    assert err.__cause__ is None


# ---------------------------------------------------------------------------
# WU7: injector must use extension service-worker context, not tab context
# ---------------------------------------------------------------------------


def test_injector_uses_extension_sw_context_method() -> None:
    """Injector must call inject_storage_config_to_extension, not inject_storage_config.

    inject_storage_config runs JS in a normal tab where chrome.storage.local
    does not exist — a silent no-op. inject_storage_config_to_extension attaches
    to the extension service-worker target and writes to chrome.storage.local.
    """
    from cli.real_clearance_composition import make_extension_config_injector

    loop = asyncio.new_event_loop()
    engine = MagicMock()
    engine.inject_storage_config_to_extension = AsyncMock()
    engine.inject_storage_config = AsyncMock()

    _url_patch = {"SCRAPING__TARGET_URL": "https://example.com"}
    with (
        patch("cli.real_clearance_composition.dotenv_values", return_value={}),
        patch.dict(os.environ, _url_patch, clear=False),
    ):
        injector = make_extension_config_injector(engine=engine, config={}, loop=loop)
        try:
            injector()
        finally:
            loop.close()

    engine.inject_storage_config_to_extension.assert_called_once()
    engine.inject_storage_config.assert_not_called()


# ---------------------------------------------------------------------------
# WU6: allowed_clearance_domain must be included in inject_storage_config call
# ---------------------------------------------------------------------------


def test_injector_includes_allowed_clearance_domain() -> None:
    """inject_storage_config_to_extension must include allowed_clearance_domain."""
    from cli.real_clearance_composition import make_extension_config_injector

    engine = MagicMock()
    engine.inject_storage_config_to_extension = AsyncMock()

    config = {
        "work_server_url": "http://127.0.0.1:9731",
        "work_server_token": "tok",
        "profile_id": "smoke",
        "worker_id": "smoke",
        "disable_task_polling": True,
    }

    _url_patch = {"SCRAPING__TARGET_URL": "https://example.com"}
    loop = asyncio.new_event_loop()
    with (
        patch("cli.real_clearance_composition.dotenv_values", return_value={}),
        patch.dict(os.environ, _url_patch, clear=False),
    ):
        injector = make_extension_config_injector(
            engine=engine, config=config, loop=loop
        )
        try:
            injector()
        finally:
            loop.close()

    call_config = engine.inject_storage_config_to_extension.call_args[0][0]
    assert call_config.get("allowed_clearance_domain") == "example.com", (
        "inject_storage_config must receive allowed_clearance_domain='example.com', "
        f"got: {call_config.get('allowed_clearance_domain')!r}"
    )


# ---------------------------------------------------------------------------
# WU6: injection domain must derive from the same URL source as navigation
# ---------------------------------------------------------------------------


def test_injection_domain_consistent_with_navigation_url() -> None:
    """allowed_clearance_domain must equal the hostname of the navigation target URL.

    Both make_extension_config_injector and make_target_navigator call _resolve_nav_url
    independently. This test guards that both factories resolve to the same source,
    so the extension always whitelists exactly the domain Chrome will navigate to.
    """
    from urllib.parse import urlparse

    from cli.real_clearance_composition import (
        make_extension_config_injector,
        make_target_navigator,
    )

    inj_engine = MagicMock()
    inj_engine.inject_storage_config_to_extension = AsyncMock()
    nav_engine = MagicMock()
    nav_engine.navigate = AsyncMock()

    _synthetic_url = "https://test.example.com/path"

    loop = asyncio.new_event_loop()
    try:
        _url_env = {"SCRAPING__TARGET_URL": _synthetic_url}
        with (
            patch("cli.real_clearance_composition.dotenv_values", return_value={}),
            patch.dict(os.environ, _url_env, clear=False),
        ):
            injector = make_extension_config_injector(
                engine=inj_engine, config={}, loop=loop
            )
            navigator = make_target_navigator(engine=nav_engine, loop=loop)
            injector()
            navigator()
    finally:
        loop.close()

    injected_domain = inj_engine.inject_storage_config_to_extension.call_args[0][0].get(
        "allowed_clearance_domain"
    )
    navigated_url = nav_engine.navigate.call_args[0][0]
    expected_domain = urlparse(navigated_url).hostname

    assert injected_domain == expected_domain, (
        f"allowed_clearance_domain {injected_domain!r} must equal the hostname "
        f"of the navigation URL {navigated_url!r} (expected {expected_domain!r})"
    )
