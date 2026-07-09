"""Generic async CRUD repository base.

Concrete domains subclass BaseRepository[Model] and set _model_class.
The caller owns the transaction — this class never commits.

Usage:
    class PlayerRepository(BaseRepository[Player]):
        _model_class = Player
"""

from abc import ABC
from typing import Any, ClassVar

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase

from core.exceptions.repository import DuplicateError, RepositoryError


class BaseRepository[T: DeclarativeBase](ABC):
    """Generic async CRUD repository.

    Subclasses MUST define _model_class as a class variable.
    The caller manages commits/rollbacks via the AsyncSession context manager.
    """

    _model_class: ClassVar[type[DeclarativeBase]]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # Only enforce on concrete subclasses (not abstract intermediaries).
        if not getattr(cls, "__abstractmethods__", None) and not hasattr(
            cls, "_model_class"
        ):
            raise TypeError(
                f"{cls.__name__} must define _model_class as a class variable"
            )

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, id: int) -> T | None:
        """Fetch entity by primary key. Returns None if absent."""
        try:
            return await self._session.get(
                self._model_class, id  # type: ignore[arg-type]
            )
        except SQLAlchemyError as exc:
            raise RepositoryError("get failed", operation="get", cause=exc) from exc

    async def create(self, entity: T) -> T:
        """Persist a new entity. Flushes but does NOT commit — caller owns the tx."""
        try:
            self._session.add(entity)
            await self._session.flush()
            await self._session.refresh(entity)
            return entity
        except IntegrityError as exc:
            raise DuplicateError(
                "create failed — possible duplicate", cause=exc
            ) from exc
        except SQLAlchemyError as exc:
            raise RepositoryError(
                "create failed", operation="create", cause=exc
            ) from exc

    async def update(self, entity: T) -> T:
        """Merge changes into the session and flush."""
        try:
            merged = await self._session.merge(entity)
            await self._session.flush()
            return merged
        except SQLAlchemyError as exc:
            raise RepositoryError(
                "update failed", operation="update", cause=exc
            ) from exc

    async def delete(self, id: int) -> bool:
        """Remove entity by primary key. Returns True if deleted, False if not found."""
        try:
            entity = await self._session.get(self._model_class, id)
            if entity is None:
                return False
            await self._session.delete(entity)
            await self._session.flush()
            return True
        except SQLAlchemyError as exc:
            raise RepositoryError(
                "delete failed", operation="delete", cause=exc
            ) from exc

    async def list(self, **filters: Any) -> list[T]:
        """Return all matching entities, optionally filtered by keyword arguments."""
        try:
            stmt = select(self._model_class)
            for attr, value in filters.items():
                stmt = stmt.where(getattr(self._model_class, attr) == value)
            result = await self._session.execute(stmt)
            return list(result.scalars().all())  # type: ignore[arg-type]
        except SQLAlchemyError as exc:
            raise RepositoryError(
                "list failed", operation="list", cause=exc
            ) from exc
