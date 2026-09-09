"""Tests for target URL scheme validation."""
import pytest

from cli.url_validation import extract_hostname, validate_target_url


class TestValidateTargetUrl:
    # --- Accepted ---
    def test_accepts_http_url(self) -> None:
        url = "http://example.com/path"
        assert validate_target_url(url) == url

    def test_accepts_https_url(self) -> None:
        assert validate_target_url("https://example.com") == "https://example.com"

    def test_accepts_http_with_port(self) -> None:
        assert validate_target_url("http://localhost:9731") == "http://localhost:9731"

    # --- Rejected: bad scheme ---
    def test_rejects_javascript_scheme(self) -> None:
        with pytest.raises(ValueError, match="http or https"):
            validate_target_url("javascript:alert(1)")

    def test_rejects_file_scheme(self) -> None:
        with pytest.raises(ValueError, match="http or https"):
            validate_target_url("file:///etc/passwd")

    def test_rejects_data_scheme(self) -> None:
        with pytest.raises(ValueError, match="http or https"):
            validate_target_url("data:text/html,<h1>x</h1>")

    def test_rejects_ftp_scheme(self) -> None:
        with pytest.raises(ValueError, match="http or https"):
            validate_target_url("ftp://example.com")

    # --- Rejected: malformed ---
    def test_rejects_scheme_less(self) -> None:
        with pytest.raises(ValueError, match="scheme"):
            validate_target_url("example.com/path")

    def test_rejects_protocol_relative(self) -> None:
        with pytest.raises(ValueError, match="scheme"):
            validate_target_url("//example.com/path")

    def test_rejects_empty(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            validate_target_url("")

    def test_rejects_whitespace(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            validate_target_url("   ")

    # --- Rejected: userinfo ---
    def test_rejects_userinfo(self) -> None:
        with pytest.raises(ValueError, match="userinfo"):
            validate_target_url("https://user:pass@example.com")

    def test_rejects_username_only(self) -> None:
        with pytest.raises(ValueError, match="userinfo"):
            validate_target_url("https://user@example.com")

    # --- Sanitization: raw URL not in exception ---
    def test_error_does_not_expose_raw_url_for_bad_scheme(self) -> None:
        url = "javascript:alert(1)"
        with pytest.raises(ValueError) as exc_info:
            validate_target_url(url)
        assert url not in str(exc_info.value)
        assert "javascript" not in str(exc_info.value)

    def test_error_does_not_expose_raw_url_for_file_scheme(self) -> None:
        url = "file:///etc/passwd"
        with pytest.raises(ValueError) as exc_info:
            validate_target_url(url)
        assert url not in str(exc_info.value)
        assert "/etc/passwd" not in str(exc_info.value)

    # --- IP literal rejection ---
    def test_rejects_ipv4_literal(self) -> None:
        with pytest.raises(ValueError, match="named host"):
            validate_target_url("http://192.168.1.1/path")

    def test_rejects_ipv6_literal(self) -> None:
        with pytest.raises(ValueError, match="named host"):
            validate_target_url("http://[::1]/path")

    # --- Whitespace normalization ---
    def test_strips_leading_whitespace(self) -> None:
        assert validate_target_url("  https://example.com") == "https://example.com"

    def test_strips_trailing_whitespace(self) -> None:
        result = validate_target_url("https://example.com  ")
        assert result == "https://example.com"

    def test_whitespace_only_is_empty(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            validate_target_url("   ")

    # --- Sanitization: no IP in error ---
    def test_ip_error_does_not_expose_raw_ip(self) -> None:
        url = "http://192.168.1.1"
        with pytest.raises(ValueError) as exc_info:
            validate_target_url(url)
        assert "192.168.1.1" not in str(exc_info.value)


class TestExtractHostname:
    def test_extracts_hostname_from_http(self) -> None:
        assert extract_hostname("http://example.com/path") == "example.com"

    def test_extracts_hostname_strips_port(self) -> None:
        assert extract_hostname("http://localhost:9731") == "localhost"

    def test_extracts_hostname_from_https(self) -> None:
        assert extract_hostname("https://sub.example.com") == "sub.example.com"
