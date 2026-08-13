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


class TestRedactSensitiveGaps:
    """CP1.4 RED — keys not yet covered by _SENSITIVE_SUBSTRINGS.

    Each test asserts that a key in the current gap set is redacted.
    All fail until _SENSITIVE_SUBSTRINGS is extended in CP1.5.
    Placeholder-only values are used throughout — no real secrets.
    """

    # ------------------------------------------------------------------
    # Cookie variants
    # ------------------------------------------------------------------

    def test_cookie_key_is_redacted(self) -> None:
        """'cookie' key must be redacted (gap: not in current substrings)."""
        event_dict: dict[str, Any] = {"cookie": "<TEST_COOKIE_VALUE>", "url": "https://fbref.com"}
        result = _redact_sensitive(None, None, event_dict)
        assert result["cookie"] == "[REDACTED]", (
            f"Expected [REDACTED] but got: {result['cookie']!r}. "
            "'cookie' is not yet in _SENSITIVE_SUBSTRINGS."
        )

    def test_set_cookie_key_is_redacted(self) -> None:
        """'set-cookie' key must be redacted (gap: hyphenated header name)."""
        event_dict: dict[str, Any] = {
            "set-cookie": "<TEST_SET_COOKIE_VALUE>",
            "status": 200,
        }
        result = _redact_sensitive(None, None, event_dict)
        assert result["set-cookie"] == "[REDACTED]", (
            f"Expected [REDACTED] but got: {result['set-cookie']!r}. "
            "'set-cookie' is not yet in _SENSITIVE_SUBSTRINGS."
        )

    def test_response_cookies_key_is_redacted(self) -> None:
        """Compound key 'response_cookies' must be redacted via 'cookie' substring."""
        event_dict: dict[str, Any] = {"response_cookies": "<TEST_COOKIE_VALUE>"}
        result = _redact_sensitive(None, None, event_dict)
        assert result["response_cookies"] == "[REDACTED]", (
            f"Expected [REDACTED] but got: {result['response_cookies']!r}."
        )

    # ------------------------------------------------------------------
    # Authorization
    # ------------------------------------------------------------------

    def test_authorization_key_is_redacted(self) -> None:
        """'authorization' key must be redacted (gap: HTTP header name)."""
        event_dict: dict[str, Any] = {
            "authorization": "<TEST_AUTHORIZATION_VALUE>",
            "method": "POST",
        }
        result = _redact_sensitive(None, None, event_dict)
        assert result["authorization"] == "[REDACTED]", (
            f"Expected [REDACTED] but got: {result['authorization']!r}. "
            "'authorization' is not yet in _SENSITIVE_SUBSTRINGS."
        )

    def test_bearer_token_in_authorization_header_key_is_redacted(self) -> None:
        """'auth_header' compound key must be redacted via 'auth' substring."""
        event_dict: dict[str, Any] = {"auth_header": "Bearer <TEST_BEARER_TOKEN>"}
        result = _redact_sensitive(None, None, event_dict)
        assert result["auth_header"] == "[REDACTED]", (
            f"Expected [REDACTED] but got: {result['auth_header']!r}. "
            "'auth_header' is not yet in _SENSITIVE_SUBSTRINGS."
        )

    # ------------------------------------------------------------------
    # HTML / body
    # ------------------------------------------------------------------

    def test_raw_html_key_is_redacted(self) -> None:
        """'raw_html' key must be redacted (gap: HTML response content)."""
        event_dict: dict[str, Any] = {"raw_html": "<TEST_RAW_HTML>", "url": "https://fbref.com"}
        result = _redact_sensitive(None, None, event_dict)
        assert result["raw_html"] == "[REDACTED]", (
            f"Expected [REDACTED] but got: {result['raw_html']!r}. "
            "'html' substring is not yet in _SENSITIVE_SUBSTRINGS."
        )

    def test_response_body_key_is_redacted(self) -> None:
        """'response_body' key must be redacted (gap: raw response body)."""
        event_dict: dict[str, Any] = {"response_body": "<TEST_RAW_HTML>"}
        result = _redact_sensitive(None, None, event_dict)
        assert result["response_body"] == "[REDACTED]", (
            f"Expected [REDACTED] but got: {result['response_body']!r}. "
            "'body' substring is not yet in _SENSITIVE_SUBSTRINGS."
        )

    # ------------------------------------------------------------------
    # CDP / browser state
    # ------------------------------------------------------------------

    def test_cdp_payload_key_is_redacted(self) -> None:
        """'cdp_payload' key must be redacted (gap: CDP message content)."""
        event_dict: dict[str, Any] = {
            "cdp_payload": "<TEST_CDP_PAYLOAD>",
            "session_id": "<session-id>",
        }
        result = _redact_sensitive(None, None, event_dict)
        assert result["cdp_payload"] == "[REDACTED]", (
            f"Expected [REDACTED] but got: {result['cdp_payload']!r}. "
            "'cdp' substring is not yet in _SENSITIVE_SUBSTRINGS."
        )

    def test_cdp_state_key_is_redacted(self) -> None:
        """'cdp_state' key must be redacted (gap: CDP session state blob)."""
        event_dict: dict[str, Any] = {"cdp_state": "<TEST_CDP_PAYLOAD>"}
        result = _redact_sensitive(None, None, event_dict)
        assert result["cdp_state"] == "[REDACTED]", (
            f"Expected [REDACTED] but got: {result['cdp_state']!r}."
        )

    # ------------------------------------------------------------------
    # Browser profile
    # ------------------------------------------------------------------

    def test_profile_path_key_is_redacted(self) -> None:
        """'profile_path' key must be redacted (gap: browser profile directory path)."""
        event_dict: dict[str, Any] = {"profile_path": "<TEST_BROWSER_PROFILE_PATH>"}
        result = _redact_sensitive(None, None, event_dict)
        assert result["profile_path"] == "[REDACTED]", (
            f"Expected [REDACTED] but got: {result['profile_path']!r}. "
            "'profile' substring is not yet in _SENSITIVE_SUBSTRINGS."
        )

    def test_browser_profile_key_is_redacted(self) -> None:
        """'browser_profile' compound key must be redacted via 'profile' substring."""
        event_dict: dict[str, Any] = {"browser_profile": "<TEST_BROWSER_PROFILE_PATH>"}
        result = _redact_sensitive(None, None, event_dict)
        assert result["browser_profile"] == "[REDACTED]", (
            f"Expected [REDACTED] but got: {result['browser_profile']!r}."
        )

    # ------------------------------------------------------------------
    # Database URL
    # ------------------------------------------------------------------

    def test_db_url_key_is_redacted(self) -> None:
        """'db_url' key must be redacted (gap: database connection string)."""
        event_dict: dict[str, Any] = {"db_url": "<TEST_DB_URL>", "pool_size": 5}
        result = _redact_sensitive(None, None, event_dict)
        assert result["db_url"] == "[REDACTED]", (
            f"Expected [REDACTED] but got: {result['db_url']!r}. "
            "'db_url' is not yet in _SENSITIVE_SUBSTRINGS."
        )

    def test_database_url_key_is_redacted(self) -> None:
        """'database_url' key must be redacted (gap: full database connection URL)."""
        event_dict: dict[str, Any] = {"database_url": "<TEST_DB_URL>"}
        result = _redact_sensitive(None, None, event_dict)
        assert result["database_url"] == "[REDACTED]", (
            f"Expected [REDACTED] but got: {result['database_url']!r}."
        )

    # ------------------------------------------------------------------
    # Nested gaps
    # ------------------------------------------------------------------

    def test_nested_cookie_in_headers_dict_is_redacted(self) -> None:
        """Cookie key nested inside a headers dict must be redacted."""
        event_dict: dict[str, Any] = {
            "request": {
                "cookie": "<TEST_COOKIE_VALUE>",
                "user-agent": "Mozilla/5.0",
            }
        }
        result = _redact_sensitive(None, None, event_dict)
        assert result["request"]["cookie"] == "[REDACTED]", (
            f"Expected [REDACTED] but got: {result['request']['cookie']!r}."
        )
