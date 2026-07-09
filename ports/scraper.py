"""Generic async scraper base with retry and exponential backoff.

Concrete scrapers implement parse(html) and receive a ScrapingEngine
and ScrapingSettings at construction. fetch_and_parse() orchestrates
the fetch → parse pipeline with retry on transient failures.

Usage:
    class PlayerScraper(BaseScraper):
        async def parse(self, html: str) -> PlayerRawData:
            ...
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Protocol

from pydantic import BaseModel

from core.exceptions.scraper import PageLoadError, RateLimitError, ScraperError
from ports.browser import ScrapingEngine

logger = logging.getLogger(__name__)


class ScraperConfig(Protocol):
    """Minimal config contract required by BaseScraper.

    Any object with these three attributes satisfies the protocol —
    ScrapingSettings from config.settings does so structurally.
    """

    max_retries: int
    base_delay: float
    max_delay: float


class BaseScraper(ABC):
    """Abstract scraper.

    Subclasses must implement parse(html). fetch_and_parse() retries on
    PageLoadError and RateLimitError; other ScraperError subtypes propagate
    immediately. Never raises bare Exception.
    """

    def __init__(self, engine: ScrapingEngine, settings: ScraperConfig) -> None:
        self._engine = engine
        self._settings = settings

    @abstractmethod
    async def parse(self, html: str) -> BaseModel:
        """Parse fetched HTML into a Pydantic model (RawData subtype)."""
        ...

    async def fetch_and_parse(self, url: str) -> BaseModel:
        """Fetch url and parse, retrying on transient errors with exponential backoff.

        Retries on PageLoadError or RateLimitError up to settings.max_retries times.
        Any other ScraperError propagates immediately.
        Raises the last ScraperError after all retries are exhausted.
        """
        last_error: ScraperError | None = None

        for attempt in range(1, self._settings.max_retries + 1):
            try:
                logger.info(
                    "Fetching URL",
                    extra={"url": url, "attempt": attempt},
                )
                html = await self._engine.fetch(url)
                return await self.parse(html)
            except (PageLoadError, RateLimitError) as exc:
                last_error = exc
                if attempt < self._settings.max_retries:
                    delay = min(
                        self._settings.base_delay * (2 ** (attempt - 1)),
                        self._settings.max_delay,
                    )
                    logger.warning(
                        "Fetch failed, retrying",
                        extra={
                            "url": url,
                            "attempt": attempt,
                            "delay": delay,
                            "error": str(exc),
                        },
                    )
                    await asyncio.sleep(delay)
            except ScraperError:
                raise

        raise last_error or PageLoadError("fetch failed after retries", url=url)
