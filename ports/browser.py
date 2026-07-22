"""Abstract browser engine contract.

Concrete implementations (e.g. PydollEngine) wrap a real browser/CDP client.
Tests use in-file mock subclasses — no real browser required at unit-test time.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class ScrapingEngine(ABC):
    """Abstract browser engine. Concrete implementations wrap pydoll-python."""

    @abstractmethod
    async def fetch(self, url: str) -> str:
        """Fetch the HTML content of the given URL and return it as a string."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Release browser resources (close tabs, sessions, CDP connections)."""
        ...

    async def __aenter__(self) -> ScrapingEngine:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()


class ScriptableEngine(ScrapingEngine):
    """ScrapingEngine subtype that additionally supports JS execution and live page source.

    Concrete implementations that drive a real browser (e.g. PydollEngine) should
    extend this class rather than ScrapingEngine directly.
    """

    @abstractmethod
    async def execute_script(self, script: str) -> None:
        """Execute arbitrary JavaScript in the current page context."""
        ...

    @abstractmethod
    async def get_page_source(self) -> str:
        """Return the current page's outer HTML without navigating."""
        ...
