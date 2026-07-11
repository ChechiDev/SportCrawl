"""Tests for migrations/env.py Settings fallback and exception handling.

Validates that env.py emits the correct log levels and correctly propagates
unexpected exceptions when loading application Settings.

Implementation note: env.py executes top-level code at import time (Settings
load, alembic context setup, migration dispatch). Tests must control the import
environment via sys.modules patching and clear the module cache between runs.
"""

import logging
import sys
import types
import unittest.mock as mock

import pytest
from pydantic import ValidationError


def _make_alembic_mock() -> tuple[mock.MagicMock, mock.MagicMock]:
    """Return (alembic_mock, context_mock) suitable for patching env.py imports.

    env.py does `from alembic import context`, so the `alembic` mock must have
    a `.context` attribute that equals the context mock we control.

    We use is_offline_mode=True so env.py calls run_migrations_offline() at the
    bottom, which only calls context.configure() and context.begin_transaction()
    — both mocked — rather than trying to connect to a real database.
    """
    context_mock = mock.MagicMock()
    context_mock.config.config_file_name = None  # skips fileConfig()
    # attributes.get() returns None → no injected URL
    context_mock.config.attributes = mock.MagicMock()
    context_mock.config.attributes.get.return_value = None
    # Use offline mode so the bottom of env.py calls run_migrations_offline()
    # which only uses mocked context.configure() + begin_transaction().
    context_mock.is_offline_mode.return_value = True

    alembic_mock = mock.MagicMock()
    alembic_mock.context = context_mock

    return alembic_mock, context_mock


def _clear_env_module() -> None:
    """Remove env.py from sys.modules to force top-level re-execution on next import."""
    for key in list(sys.modules.keys()):
        if "infrastructure.persistence.migrations.env" in key:
            del sys.modules[key]


def _base_module_patches(
    alembic_mock: mock.MagicMock,
    context_mock: mock.MagicMock,
    extra_patches: dict[str, object] | None = None,
) -> dict[str, object]:
    """Build the sys.modules patch dict for env.py import tests."""
    patches: dict[str, object] = {
        "alembic": alembic_mock,
        "alembic.context": context_mock,
    }
    if extra_patches:
        patches.update(extra_patches)
    return patches


class TestEnvMigrationsSettingsFallback:
    """T1: env.py logs WARNING (not DEBUG) when Settings load falls back."""

    def test_env_fallback_emits_warning_on_import_error(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """ImportError during Settings load emits WARNING with 'fallback' in message."""
        alembic_mock, context_mock = _make_alembic_mock()
        _clear_env_module()

        patches = _base_module_patches(
            alembic_mock,
            context_mock,
            # None in sys.modules causes ImportError on
            # 'from config.settings import Settings'
            {"config.settings": None},
        )

        with mock.patch.dict(sys.modules, patches):
            with caplog.at_level(logging.WARNING):
                import infrastructure.persistence.migrations.env  # noqa: PLC0415, F401

        warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any(
            "falling back" in r.getMessage().lower() for r in warning_records
        ), (
            f"Expected a WARNING containing 'falling back', "
            f"got records: {[(r.levelno, r.getMessage()) for r in caplog.records]}"
        )

    def test_env_fallback_does_not_emit_debug_on_import_error(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """ImportError during Settings load must NOT emit a DEBUG fallback message."""
        alembic_mock, context_mock = _make_alembic_mock()
        _clear_env_module()

        patches = _base_module_patches(
            alembic_mock, context_mock, {"config.settings": None}
        )

        with mock.patch.dict(sys.modules, patches):
            with caplog.at_level(logging.DEBUG):
                import infrastructure.persistence.migrations.env  # noqa: PLC0415, F401

        debug_fallback_records = [
            r
            for r in caplog.records
            if r.levelno == logging.DEBUG and "falling back" in r.getMessage().lower()
        ]
        assert debug_fallback_records == [], (
            f"Expected no DEBUG fallback message, "
            f"got: {[r.getMessage() for r in debug_fallback_records]}"
        )


class TestEnvMigrationsUnexpectedException:
    """T2: env.py re-raises unexpected exceptions after logging at ERROR level."""

    def test_env_unexpected_exception_propagates(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """RuntimeError during Settings load propagates out of env module import."""
        alembic_mock, context_mock = _make_alembic_mock()
        _clear_env_module()

        # Build a fake config.settings module whose Settings() raises RuntimeError
        fake_settings_module = types.ModuleType("config.settings")

        class _BrokenSettings:
            def __init__(self, **_kwargs: object) -> None:
                raise RuntimeError("Simulated unexpected failure")

        fake_settings_module.Settings = _BrokenSettings  # type: ignore[attr-defined]
        fake_settings_module.ValidationError = ValidationError  # type: ignore[attr-defined]  # noqa: E501

        patches = _base_module_patches(
            alembic_mock, context_mock, {"config.settings": fake_settings_module}
        )

        with mock.patch.dict(sys.modules, patches):
            with caplog.at_level(logging.ERROR):
                with pytest.raises(
                    RuntimeError, match="Simulated unexpected failure"
                ):
                    # noqa: PLC0415
                    import infrastructure.persistence.migrations.env  # noqa: F401

    def test_env_unexpected_exception_logs_error(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """RuntimeError during Settings load is logged at ERROR before re-raise."""
        alembic_mock, context_mock = _make_alembic_mock()
        _clear_env_module()

        fake_settings_module = types.ModuleType("config.settings")

        class _BrokenSettings:
            def __init__(self, **_kwargs: object) -> None:
                raise RuntimeError("Simulated unexpected failure")

        fake_settings_module.Settings = _BrokenSettings  # type: ignore[attr-defined]
        fake_settings_module.ValidationError = ValidationError  # type: ignore[attr-defined]  # noqa: E501

        patches = _base_module_patches(
            alembic_mock, context_mock, {"config.settings": fake_settings_module}
        )

        with mock.patch.dict(sys.modules, patches):
            with caplog.at_level(logging.ERROR):
                with pytest.raises(RuntimeError):
                    # noqa: PLC0415
                    import infrastructure.persistence.migrations.env  # noqa: F401

        error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert error_records, (
            f"Expected at least one ERROR log record, "
            f"got: {[(r.levelno, r.message) for r in caplog.records]}"
        )
