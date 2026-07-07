"""Service exception hierarchy.

ServiceError is the top-level exception callers see from BaseService.
ScraperError and RepositoryError must not propagate past the service boundary.
"""


class ServiceError(Exception):
    """Base exception for all service-layer failures."""

    def __init__(
        self,
        message: str,
        *,
        cause: Exception | None = None,
    ) -> None:
        super().__init__(message)
        self.cause = cause
