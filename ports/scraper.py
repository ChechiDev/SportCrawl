"""Generic async scraper base with retry and exponential backoff.

Concrete scrapers implement parse(html) and receive a ScrapingEngine
and ScrapingSettings at construction. fetch_and_parse() orchestrates
the fetch → parse pipeline with retry on transient failures.

Usage:
    class PlayerScraper(BaseScraper[PlayerRawData]):
        async def parse(self, html: str) -> PlayerRawData:
            ...
"""

import asyncio
import io
import logging
from abc import ABC, abstractmethod
from typing import Protocol, TypeVar

import pandas as pd  # type: ignore[import-untyped]
from bs4 import BeautifulSoup
from pydantic import BaseModel

from core.exceptions.scraper import PageLoadError, RateLimitError, ScraperError
from ports.browser import ScrapingEngine

logger = logging.getLogger(__name__)

T_co = TypeVar("T_co", bound=BaseModel, covariant=True)


class ScraperConfig(Protocol):
    """Minimal config contract required by BaseScraper.

    Any object with these three attributes satisfies the protocol —
    ScrapingSettings from config.settings does so structurally.
    """

    max_retries: int
    base_delay: float
    max_delay: float


class BaseScraper[T_co](ABC):
    """Abstract scraper.

    Subclasses must implement parse(html). fetch_and_parse() retries on
    PageLoadError and RateLimitError; other ScraperError subtypes propagate
    immediately. Never raises bare Exception.
    """

    def __init__(self, engine: ScrapingEngine, settings: ScraperConfig) -> None:
        self._engine = engine
        self._settings = settings

    @abstractmethod
    async def parse(self, html: str) -> T_co:
        """Parse fetched HTML into a Pydantic model (RawData subtype)."""
        ...

    async def fetch_and_parse(self, url: str) -> T_co:
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


class BaseMultiTableScraper(BaseScraper[T_co]):
    """Abstract scraper that extracts HTML tables keyed by their id attribute.

    parse() does a BeautifulSoup pre-pass to find all <table id=...> elements,
    builds a {table_id: DataFrame} dict, then delegates to parse_tables().
    Tables without an id attribute are skipped. If no id-bearing tables are
    found, ScraperError is raised before parse_tables() is called.

    Concrete scrapers access tables by semantic id: tables["stats_standard"].
    """

    async def parse(self, html: str) -> T_co:
        soup = BeautifulSoup(html, "lxml")
        tables: dict[str, pd.DataFrame] = {
            t["id"]: pd.read_html(io.StringIO(str(t)))[0]  # type: ignore[misc]
            for t in soup.find_all("table", id=True)
        }
        if not tables:
            raise ScraperError("no tables with id attribute found in page")
        return await self.parse_tables(tables)

    @abstractmethod
    async def parse_tables(self, tables: dict[str, pd.DataFrame]) -> T_co:
        """Parse id-keyed DataFrames into a domain model."""
        ...
