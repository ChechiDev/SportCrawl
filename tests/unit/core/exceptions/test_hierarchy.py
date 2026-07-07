"""Tests for the exception hierarchy.

All tests must pass without a database. RED phase: these tests will fail
until the exception modules are created.
"""

import pytest

from core.exceptions.repository import (
    DuplicateError,
    NotFoundError,
    RepositoryError,
)
from core.exceptions.scraper import (
    PageLoadError,
    ParsingError,
    RateLimitError,
    ScraperError,
)
from core.exceptions.service import ServiceError


class TestScraperErrorHierarchy:
    def test_scraper_error_is_exception(self) -> None:
        err = ScraperError("base scraper error")
        assert isinstance(err, Exception)

    def test_page_load_error_caught_as_scraper_error(self) -> None:
        with pytest.raises(ScraperError):
            raise PageLoadError("page failed to load")

    def test_parsing_error_caught_as_scraper_error(self) -> None:
        with pytest.raises(ScraperError):
            raise ParsingError("could not parse html")

    def test_rate_limit_error_caught_as_scraper_error(self) -> None:
        with pytest.raises(ScraperError):
            raise RateLimitError("rate limit exceeded")

    def test_scraper_error_stores_message(self) -> None:
        err = ScraperError("something went wrong", url="https://example.com")
        assert str(err) == "something went wrong"
        assert err.url == "https://example.com"

    def test_scraper_error_optional_kwargs_default_to_none(self) -> None:
        err = ScraperError("bare error")
        assert err.url is None
        assert err.cause is None

    def test_page_load_error_stores_url(self) -> None:
        err = PageLoadError("failed", url="https://fbref.com")
        assert err.url == "https://fbref.com"

    def test_parsing_error_stores_cause(self) -> None:
        original = ValueError("bad value")
        err = ParsingError("parse failed", cause=original)
        assert err.cause is original

    def test_rate_limit_error_stores_url_and_cause(self) -> None:
        original = ConnectionError("conn reset")
        err = RateLimitError("rate limit", url="https://fbref.com", cause=original)
        assert err.url == "https://fbref.com"
        assert err.cause is original


class TestRepositoryErrorHierarchy:
    def test_repository_error_is_exception(self) -> None:
        err = RepositoryError("base repo error")
        assert isinstance(err, Exception)

    def test_not_found_error_caught_as_repository_error(self) -> None:
        with pytest.raises(RepositoryError):
            raise NotFoundError("entity not found")

    def test_duplicate_error_caught_as_repository_error(self) -> None:
        with pytest.raises(RepositoryError):
            raise DuplicateError("entity already exists")

    def test_repository_error_stores_message(self) -> None:
        err = RepositoryError("something failed", operation="get")
        assert str(err) == "something failed"
        assert err.operation == "get"

    def test_repository_error_optional_kwargs_default_to_none(self) -> None:
        err = RepositoryError("bare error")
        assert err.operation is None
        assert err.cause is None

    def test_not_found_error_stores_operation(self) -> None:
        err = NotFoundError("not found", operation="get_by_id")
        assert err.operation == "get_by_id"

    def test_duplicate_error_stores_cause(self) -> None:
        original = RuntimeError("integrity constraint")
        err = DuplicateError("duplicate key", cause=original)
        assert err.cause is original


class TestServiceErrorHierarchy:
    def test_service_error_is_exception(self) -> None:
        err = ServiceError("service failure")
        assert isinstance(err, Exception)

    def test_service_error_stores_message(self) -> None:
        err = ServiceError("operation failed")
        assert str(err) == "operation failed"

    def test_scraper_error_is_not_service_error(self) -> None:
        """ServiceError and ScraperError are independent hierarchies."""
        err = ScraperError("scraper issue")
        assert not isinstance(err, ServiceError)

    def test_repository_error_is_not_service_error(self) -> None:
        """ServiceError and RepositoryError are independent hierarchies."""
        err = RepositoryError("repo issue")
        assert not isinstance(err, ServiceError)
