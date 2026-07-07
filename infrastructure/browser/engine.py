"""Abstract browser engine contract.

Concrete implementations (e.g. PydollEngine) wrap a real browser/CDP client.
Tests use in-file mock subclasses — no real browser required at unit-test time.

Note: PydollEngine is deferred to Phase 3 (PR 3) after the pydoll-python API spike.
"""

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
