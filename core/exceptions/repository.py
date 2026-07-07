"""Repository exception hierarchy.

RepositoryError is the base. All repository errors carry optional operation and cause.
Callers catch RepositoryError (or a specific subtype). Never raise bare Exception.
"""


class RepositoryError(Exception):
    """Base exception for all persistence failures."""

    def __init__(
        self,
        message: str,
        *,
        operation: str | None = None,
        cause: Exception | None = None,
    ) -> None:
        super().__init__(message)
        self.operation = operation
        self.cause = cause


class NotFoundError(RepositoryError):
    """Raised when an expected entity is absent from the store."""


class DuplicateError(RepositoryError):
    """Raised when an insert violates a uniqueness constraint."""
