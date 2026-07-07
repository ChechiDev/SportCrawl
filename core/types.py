"""Shared type aliases and TypeVars used across core abstractions."""

from typing import TypeVar

from sqlalchemy.orm import DeclarativeBase

T = TypeVar("T", bound=DeclarativeBase)
