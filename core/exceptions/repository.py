"""Repository exception hierarchy.

RepositoryError is the base. All repository errors carry optional operation and cause.
Callers catch RepositoryError (or a specific subtype). Never raise bare Exception.
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.exc import SQLAlchemyError


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


@asynccontextmanager
async def repo_error_context(
    operation: str, message: str
) -> AsyncGenerator[None, None]:
    try:
        yield
    except SQLAlchemyError as exc:
        raise RepositoryError(message, operation=operation, cause=exc) from exc
