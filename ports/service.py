"""Abstract service base.

Concrete domain services subclass BaseService and implement execute().
BaseService catches ScraperError and RepositoryError and re-raises them
as ServiceError so no infra-layer exception propagates to callers.

Phase 1: thin stub with an abstract entrypoint.
Phase 3: will add orchestration helpers and error-wrapping logic.
"""

from abc import ABC, abstractmethod


class BaseService(ABC):
    """Base orchestration service. Concrete domains extend this."""

    @abstractmethod
    async def execute(self) -> None:
        """Service operation entrypoint. Concrete domains override and extend this."""
        ...
