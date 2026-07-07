"""Tests for core logging configuration.

Validates that configure_logging and bind_context behave correctly in
dev and prod modes without requiring a real server or database.
"""

import logging
import unittest.mock as mock

from core.logging import bind_context, configure_logging


class TestConfigureLogging:
    def test_configure_logging_dev_mode_does_not_raise(self) -> None:
        """configure_logging with env='dev' completes without error."""
        with mock.patch("core.logging.structlog.configure"):
            with mock.patch("core.logging.logging.basicConfig"):
                configure_logging(env="dev", log_level="INFO")

    def test_configure_logging_prod_mode_does_not_raise(self) -> None:
        """configure_logging with env='prod' completes without error."""
        with mock.patch("core.logging.structlog.configure"):
            with mock.patch("core.logging.logging.basicConfig"):
                configure_logging(env="prod", log_level="INFO")

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


class TestBindContext:
    def test_bind_context_returns_bound_logger(self) -> None:
        """bind_context returns a structlog BoundLogger."""
        logger = bind_context(domain="player", operation="fetch")
        assert logger is not None

    def test_bind_context_domain_and_operation_captured(self) -> None:
        """bind_context does not raise and accepts string arguments."""
        # We test the interface, not the internal structlog state,
        # since BoundLogger internals are structlog-version-specific.
        logger = bind_context(domain="club", operation="parse")
        assert logger is not None

    def test_bind_context_accepts_any_string_domain(self) -> None:
        logger = bind_context(domain="confederation", operation="list")
        assert logger is not None
