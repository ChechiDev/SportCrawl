"""Declarative base for all SQLAlchemy ORM models."""

from typing import Any

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base; all ORM models must inherit from this class."""


class FootballBase(Base):
    """Abstract base for all football-domain ORM models.

    Subclasses must add::

        __table_args__ = {"schema": "sch_fbref_football"}

    to place their table in the sch_fbref_football schema. This class does NOT set
    __table_args__ itself because SQLAlchemy does not inherit table_args from
    abstract bases — each concrete model must declare it explicitly.
    """

    __abstract__ = True
    __schema__ = "sch_fbref_football"


class BackendBase(Base):
    """Abstract base for all backend-domain ORM models (sch_fbref_backend schema)."""

    __abstract__ = True
    __table_args__: tuple[Any, ...] | dict[str, Any] = {"schema": "sch_fbref_backend"}
