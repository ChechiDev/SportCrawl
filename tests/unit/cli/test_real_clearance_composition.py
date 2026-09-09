"""Tests for cli/real_clearance_composition.py — structural and behavioral."""
from __future__ import annotations

import asyncio
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
    engine.inject_storage_config = AsyncMock()

    config = {
        "work_server_url": "http://127.0.0.1:9731",
        "work_server_token": "tok",
        "profile_id": "smoke",
        "worker_id": "smoke",
        "disable_task_polling": True,
    }

    injector = make_extension_config_injector(engine=engine, config=config, loop=loop)
    try:
        injector()
    finally:
        loop.close()

    engine.inject_storage_config.assert_called_once_with(config)


def test_make_injector_calls_engine_inject_with_empty_config() -> None:
    """Calling the injector with an empty config dict must still invoke the engine."""
    from cli.real_clearance_composition import make_extension_config_injector

    loop = asyncio.new_event_loop()
    engine = MagicMock()
    engine.inject_storage_config = AsyncMock()

    injector = make_extension_config_injector(engine=engine, config={}, loop=loop)
    try:
        injector()
    finally:
        loop.close()

    engine.inject_storage_config.assert_called_once_with({})


def test_make_injector_raises_when_loop_closed() -> None:
    from cli.real_clearance_composition import make_extension_config_injector

    loop = asyncio.new_event_loop()
    loop.close()

    engine = MagicMock()
    injector = make_extension_config_injector(engine=engine, config={}, loop=loop)

    with pytest.raises(RuntimeError, match="not usable"):
        injector()


def test_make_injector_raises_when_loop_running() -> None:
    """Injector must refuse to run when the loop is already running."""
    from cli.real_clearance_composition import make_extension_config_injector

    async def _inner() -> None:
        loop = asyncio.get_event_loop()
        engine = MagicMock()
        injector = make_extension_config_injector(engine=engine, config={}, loop=loop)
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

    navigator = make_target_navigator(engine=engine, loop=loop)

    with patch("cli.real_clearance_composition.dotenv_values", return_value={}), \
         patch.dict("os.environ", {}, clear=True):
        with pytest.raises(RuntimeError, match="SCRAPING__TARGET_URL"):
            navigator()

    loop.close()


def test_make_navigator_raises_on_scheme_less_url() -> None:
    from cli.real_clearance_composition import make_target_navigator

    loop = asyncio.new_event_loop()
    engine = MagicMock()
    engine.navigate = AsyncMock()

    navigator = make_target_navigator(engine=engine, loop=loop)

    with patch("cli.real_clearance_composition.dotenv_values", return_value={}), \
         patch.dict("os.environ", {"SCRAPING__TARGET_URL": "//example.com"}):
        with pytest.raises(RuntimeError, match="target navigation"):
            navigator()

    loop.close()


def test_make_navigator_calls_engine_navigate() -> None:
    from cli.real_clearance_composition import make_target_navigator

    loop = asyncio.new_event_loop()
    engine = MagicMock()
    engine.navigate = AsyncMock()

    navigator = make_target_navigator(engine=engine, loop=loop)

    with patch("cli.real_clearance_composition.dotenv_values", return_value={}), \
         patch.dict("os.environ", {"SCRAPING__TARGET_URL": "https://example.com"}):
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

    navigator = make_target_navigator(engine=engine, loop=loop)

    with patch("cli.real_clearance_composition.dotenv_values", return_value={}), \
         patch.dict(
             "os.environ", {"SCRAPING__TARGET_URL": "https://secret.example.com"}
         ):
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
    nav = make_target_navigator(engine=engine, loop=loop)

    with pytest.raises(RuntimeError, match="loop is not usable"):
        nav()


def test_make_injector_restores_logger_level_on_failure() -> None:
    """make_extension_config_injector must restore pydoll logger level on failure."""
    import logging
    from unittest.mock import AsyncMock, MagicMock

    from cli.real_clearance_composition import make_extension_config_injector

    engine = MagicMock()
    engine.inject_storage_config = AsyncMock(
        side_effect=RuntimeError("inject failed")
    )

    logger = logging.getLogger("pydoll")
    orig_level = logger.level

    loop = asyncio.new_event_loop()
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

    async def _hang(url: str) -> None:
        await asyncio.sleep(9999)

    engine = MagicMock()
    engine.navigate = _hang
    with patch.object(_comp_module, "_NAV_TIMEOUT_S", 0.05):
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

    async def _hang(cfg: dict) -> None:
        await asyncio.sleep(9999)

    engine = MagicMock()
    engine.inject_storage_config = _hang
    with patch.object(_comp_module, "_INJECT_TIMEOUT_S", 0.05):
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
    navigator = make_target_navigator(engine=engine, loop=loop)

    try:
        with (
            patch(
                "cli.real_clearance_composition.dotenv_values",
                return_value={"SCRAPING__TARGET_URL": "https://from-dotenv.example.com"},
            ),
            patch.dict(
                "os.environ",
                {"SCRAPING__TARGET_URL": "https://from-env.example.com"},
                clear=False,
            ),
        ):
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

    async def _hang(url: str) -> None:
        await asyncio.sleep(9999)

    engine = MagicMock()
    engine.navigate = _hang
    engine.stop = AsyncMock()
    with patch.object(_comp_module, "_NAV_TIMEOUT_S", 0.05):
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

    async def _hang(cfg: dict) -> None:
        await asyncio.sleep(9999)

    engine = MagicMock()
    engine.inject_storage_config = _hang
    engine.stop = AsyncMock()
    with patch.object(_comp_module, "_INJECT_TIMEOUT_S", 0.05):
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

    async def _hang(url: str) -> None:
        await asyncio.sleep(9999)

    engine = MagicMock()
    engine.navigate = _hang
    engine.stop = AsyncMock(side_effect=RuntimeError("stop failed"))
    with patch.object(_comp_module, "_NAV_TIMEOUT_S", 0.05):
        nav = make_target_navigator(engine)
        loop = asyncio.new_event_loop()
        try:
            with pytest.raises(RuntimeError, match="timed out"):
                loop.run_until_complete(nav())
        finally:
            loop.close()
