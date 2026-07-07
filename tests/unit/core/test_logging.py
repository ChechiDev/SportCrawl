"""Tests for core logging configuration.

Validates that configure_logging and bind_context behave correctly in
dev and prod modes without requiring a real server or database.
"""

import logging
import unittest.mock as mock

import pytest
import structlog.testing

from core.logging import bind_context, configure_logging


class TestConfigureLogging:
    def test_configure_logging_dev_uses_console_renderer(self) -> None:
        """configure_logging with env='dev' instantiates ConsoleRenderer."""
        with mock.patch("core.logging.structlog.dev.ConsoleRenderer") as mock_console:
            with mock.patch("core.logging.logging.basicConfig"):
                configure_logging(env="dev", log_level="INFO")
            mock_console.assert_called_once()

    def test_configure_logging_prod_uses_json_renderer(self) -> None:
        """configure_logging with env='prod' instantiates JSONRenderer."""
        with mock.patch("core.logging.structlog.processors.JSONRenderer") as mock_json:
            with mock.patch("core.logging.logging.basicConfig"):
                configure_logging(env="prod", log_level="INFO")
            mock_json.assert_called_once()

    def test_configure_logging_accepts_debug_level(self) -> None:
        with mock.patch("core.logging.structlog.configure"):
            with mock.patch("core.logging.logging.basicConfig") as mock_basic:
                configure_logging(env="dev", log_level="DEBUG")
                mock_basic.assert_called_once()
                _, kwargs = mock_basic.call_args
                assert kwargs.get("level") == logging.DEBUG

    def test_configure_logging_accepts_info_level(self) -> None:
        with mock.patch("core.logging.structlog.configure"):
            with mock.patch("core.logging.logging.basicConfig") as mock_basic:
                configure_logging(env="dev", log_level="INFO")
                _, kwargs = mock_basic.call_args
                assert kwargs.get("level") == logging.INFO

    def test_configure_logging_invalid_level_raises(self) -> None:
        """An unrecognised log level raises ValueError instead of silently falling back."""
        with pytest.raises(ValueError, match="Invalid log_level"):
            configure_logging(env="dev", log_level="VERBOSE")

    def test_configure_logging_level_case_insensitive(self) -> None:
        with mock.patch("core.logging.structlog.configure"):
            with mock.patch("core.logging.logging.basicConfig") as mock_basic:
                configure_logging(env="dev", log_level="warning")
                _, kwargs = mock_basic.call_args
                assert kwargs.get("level") == logging.WARNING


class TestBindContext:
    def test_bind_context_domain_bound_in_log_output(self) -> None:
        """bind_context binds domain into every log entry emitted by the logger."""
        with structlog.testing.capture_logs() as captured:
            logger = bind_context(domain="player", operation="fetch")
            logger.info("test event")
        assert len(captured) == 1
        assert captured[0]["domain"] == "player"

    def test_bind_context_operation_bound_in_log_output(self) -> None:
        """bind_context binds operation into every log entry emitted by the logger."""
        with structlog.testing.capture_logs() as captured:
            logger = bind_context(domain="club", operation="parse")
            logger.info("test event")
        assert len(captured) == 1
        assert captured[0]["operation"] == "parse"

    def test_bind_context_both_fields_present(self) -> None:
        """domain and operation both appear in the same captured log entry."""
        with structlog.testing.capture_logs() as captured:
            logger = bind_context(domain="confederation", operation="list")
            logger.info("test event")
        assert captured[0]["domain"] == "confederation"
        assert captured[0]["operation"] == "list"
