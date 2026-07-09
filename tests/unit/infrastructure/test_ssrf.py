"""Unit tests for validate_scrape_url — pure stdlib, no DB required.

All cases hit core/security/url_validator.py directly.
No asyncpg, no testcontainers, no ScrapingEngine needed.
"""

import pytest

from core.exceptions.scraper import SSRFError
from core.security.url_validator import validate_scrape_url

ALLOWED = ["fbref.com"]


class TestValidateScrapeUrlAccepted:
    def test_https_fbref_root_is_accepted(self) -> None:
        result = validate_scrape_url("https://fbref.com/en/squads/", ALLOWED)
        assert result == "fbref.com"

    def test_subdomain_of_allowed_host_is_accepted(self) -> None:
        result = validate_scrape_url("https://widgets.fbref.com/path", ALLOWED)
        assert result == "widgets.fbref.com"

    def test_deep_path_is_accepted(self) -> None:
        result = validate_scrape_url(
            "https://fbref.com/en/comps/9/Premier-League-Stats", ALLOWED
        )
        assert result == "fbref.com"


class TestValidateScrapeUrlScheme:
    def test_http_scheme_is_rejected(self) -> None:
        with pytest.raises(SSRFError) as exc_info:
            validate_scrape_url("http://fbref.com/path", ALLOWED)
        assert exc_info.value.reason == "scheme must be https"

    def test_ftp_scheme_is_rejected(self) -> None:
        with pytest.raises(SSRFError) as exc_info:
            validate_scrape_url("ftp://fbref.com/path", ALLOWED)
        assert exc_info.value.reason == "scheme must be https"


class TestValidateScrapeUrlHost:
    def test_missing_host_is_rejected(self) -> None:
        with pytest.raises(SSRFError) as exc_info:
            validate_scrape_url("https:///path", ALLOWED)
        assert exc_info.value.reason == "missing host"


class TestValidateScrapeUrlPrivateIp:
    def test_private_ip_class_c_is_rejected(self) -> None:
        with pytest.raises(SSRFError) as exc_info:
            validate_scrape_url("https://192.168.1.1/path", ALLOWED)
        assert exc_info.value.reason == "private IP not allowed"

    def test_loopback_ip_is_rejected(self) -> None:
        with pytest.raises(SSRFError) as exc_info:
            validate_scrape_url("https://127.0.0.1/path", ALLOWED)
        assert exc_info.value.reason == "private IP not allowed"

    def test_link_local_ip_is_rejected(self) -> None:
        with pytest.raises(SSRFError) as exc_info:
            validate_scrape_url("https://169.254.169.254/path", ALLOWED)
        assert exc_info.value.reason == "private IP not allowed"


class TestValidateScrapeUrlAllowlist:
    def test_non_allowlisted_host_is_rejected(self) -> None:
        with pytest.raises(SSRFError) as exc_info:
            validate_scrape_url("https://evil.com/path", ALLOWED)
        assert exc_info.value.reason == "host not in allowed_hosts"

    def test_lookalike_host_is_rejected(self) -> None:
        with pytest.raises(SSRFError) as exc_info:
            validate_scrape_url("https://notfbref.com/path", ALLOWED)
        assert exc_info.value.reason == "host not in allowed_hosts"

    def test_multiple_allowed_hosts_are_each_accepted(self) -> None:
        allowed = ["fbref.com", "stathead.com"]
        assert validate_scrape_url("https://fbref.com/path", allowed) == "fbref.com"
        assert (
            validate_scrape_url("https://stathead.com/path", allowed) == "stathead.com"
        )
