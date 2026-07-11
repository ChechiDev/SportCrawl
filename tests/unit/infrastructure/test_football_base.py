"""Unit tests for FootballBase ORM base class.

Validates REQ-8.4: FootballBase must be a direct subclass of Base,
use the same single DeclarativeBase metadata, and be marked as abstract
so SQLAlchemy does not create a table for it.
"""

from infrastructure.persistence.models.base import Base, FootballBase


class TestFootballBase:
    """REQ-8.4: FootballBase structure and metadata contracts."""

    def test_football_base_is_abstract(self) -> None:
        """FootballBase.__abstract__ must be True to prevent table creation."""
        assert FootballBase.__abstract__ is True

    def test_football_base_is_subclass_of_base(self) -> None:
        """FootballBase must be a subclass of Base (the single DeclarativeBase)."""
        assert issubclass(FootballBase, Base)

    def test_football_base_shares_metadata_with_base(self) -> None:
        """FootballBase.metadata must be the same object as Base.metadata.

        This ensures all models use a single shared MetaData instance,
        which is required for autogenerate and migration consistency.
        """
        assert FootballBase.metadata is Base.metadata

    def test_football_base_schema_attribute(self) -> None:
        """FootballBase.__schema__ is 'sch_football' for schema targeting."""
        assert FootballBase.__schema__ == "sch_football"
