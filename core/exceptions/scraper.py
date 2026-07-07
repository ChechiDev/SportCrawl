"""Scraper exception hierarchy.

ScraperError is the base. All scraper errors carry optional url and cause.
Callers catch ScraperError (or a specific subtype). Never raise bare Exception.
"""


class ScraperError(Exception):
    """Base exception for all scraping failures."""

    def __init__(
        self,
        message: str,
        *,
        url: str | None = None,
        cause: Exception | None = None,
    ) -> None:
        super().__init__(message)
        self.url = url
        self.cause = cause


class PageLoadError(ScraperError):
    """Raised when a page cannot be fetched (network or HTTP error)."""


class ParsingError(ScraperError):
    """Raised when fetched HTML cannot be parsed into the expected structure."""


class RateLimitError(ScraperError):
    """Raised when the target site enforces a rate limit (429 or equivalent)."""
