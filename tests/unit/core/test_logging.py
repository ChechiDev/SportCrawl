"""Tests for core logging configuration.

Validates that configure_logging, bind_context, and _redact_sensitive behave
correctly in dev and prod modes without requiring a real server or database.
"""

import logging
import unittest.mock as mock
from typing import Any

import pytest
import structlog.testing

from core.logging import _redact_sensitive, bind_context, configure_logging


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
        """Unrecognised log level raises ValueError instead of silently falling back."""
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


class TestRedactSensitive:
    """Tests for the _redact_sensitive structlog processor."""

    def test_top_level_password_is_redacted(self) -> None:
        """Top-level 'password' key value is replaced with [REDACTED]."""
        event_dict: dict[str, Any] = {"password": "s3cr3t", "user": "alice"}
        result = _redact_sensitive(None, None, event_dict)
        assert result["password"] == "[REDACTED]"
        assert result["user"] == "alice"

    def test_top_level_token_is_redacted(self) -> None:
        """Top-level 'token' key value is replaced with [REDACTED]."""
        event_dict: dict[str, Any] = {"token": "abc123", "status": "ok"}
        result = _redact_sensitive(None, None, event_dict)
        assert result["token"] == "[REDACTED]"
        assert result["status"] == "ok"

    def test_nested_password_is_redacted(self) -> None:
        """'password' key nested inside a dict is redacted recursively."""
        event_dict: dict[str, Any] = {"db": {"password": "s3cr3t", "host": "localhost"}}
        result = _redact_sensitive(None, None, event_dict)
        assert result["db"]["password"] == "[REDACTED]"
        assert result["db"]["host"] == "localhost"

    def test_cf_clearance_is_redacted(self) -> None:
        """'cf_clearance' key is redacted because it contains 'clearance'."""
        event_dict: dict[str, Any] = {"cf_clearance": "abc123", "url": "https://x.com"}
        result = _redact_sensitive(None, None, event_dict)
        assert result["cf_clearance"] == "[REDACTED]"
        assert result["url"] == "https://x.com"

    def test_non_sensitive_keys_unchanged(self) -> None:
        """Keys not matching sensitive patterns pass through unmodified."""
        event_dict: dict[str, Any] = {"url": "https://example.com", "status": 200}
        result = _redact_sensitive(None, None, event_dict)
        assert result["url"] == "https://example.com"
        assert result["status"] == 200

    def test_secret_key_is_redacted(self) -> None:
        """Top-level 'secret' key value is replaced with [REDACTED]."""
        event_dict: dict[str, Any] = {"secret": "value", "event": "login"}
        result = _redact_sensitive(None, None, event_dict)
        assert result["secret"] == "[REDACTED]"
        assert result["event"] == "login"

    def test_list_with_nested_sensitive_dict(self) -> None:
        """Dicts with sensitive keys nested inside a list are each redacted."""
        event_dict: dict[str, Any] = {
            "credentials": [
                {"password": "pass1", "user": "alice"},
                {"password": "pass2", "user": "bob"},
            ]
        }
        result = _redact_sensitive(None, None, event_dict)
        assert result["credentials"][0]["password"] == "[REDACTED]"
        assert result["credentials"][0]["user"] == "alice"
        assert result["credentials"][1]["password"] == "[REDACTED]"
        assert result["credentials"][1]["user"] == "bob"

    def test_processor_signature(self) -> None:
        """_redact_sensitive is callable with (logger, name, event_dict) → dict."""
        event_dict: dict[str, Any] = {"event": "test", "token": "tok"}
        result = _redact_sensitive(object(), "test.logger", event_dict)
        assert isinstance(result, dict)
        assert result["token"] == "[REDACTED]"
        assert result["event"] == "test"
