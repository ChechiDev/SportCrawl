"""Declarative base for all SQLAlchemy ORM models."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base; all ORM models must inherit from this class."""


class FootballBase(Base):
    """Abstract base for all football-domain ORM models.

    Subclasses must add::

        __table_args__ = {"schema": "sch_football"}

    to place their table in the sch_football schema. This class does NOT set
    __table_args__ itself because SQLAlchemy does not inherit table_args from
    abstract bases — each concrete model must declare it explicitly.
    """

    __abstract__ = True
    __schema__ = "sch_football"
