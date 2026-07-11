"""Unit tests for infrastructure/persistence/migrations/_filters.py.

Tests the include_name() callback that controls which database objects
Alembic tracks during autogenerate. The function must:
- Return True for objects belonging to managed schemas
- Return False for objects in the public schema
- Return True for table-type objects
- Return True for column-type objects
"""


from infrastructure.persistence.migrations._filters import include_name


class TestIncludeNameManagedSchemas:
    """REQ-8.7: include_name returns True for whitelisted schemas."""

    def test_whitelisted_schema_sch_infra_returns_true(self) -> None:
        """sch_infra is a managed schema and must be included."""
        result = include_name(
            name="sch_infra",
            type_="schema",
            parent_names={},
        )
        assert result is True

    def test_whitelisted_schema_sch_shared_returns_true(self) -> None:
        """sch_shared is a managed schema and must be included."""
        result = include_name(
            name="sch_shared",
            type_="schema",
            parent_names={},
        )
        assert result is True

    def test_whitelisted_schema_sch_football_returns_true(self) -> None:
        """sch_football is a managed schema and must be included."""
        result = include_name(
            name="sch_football",
            type_="schema",
            parent_names={},
        )
        assert result is True

    def test_public_schema_returns_false(self) -> None:
        """public schema is NOT managed and must be excluded."""
        result = include_name(
            name="public",
            type_="schema",
            parent_names={},
        )
        assert result is False

    def test_unknown_schema_returns_false(self) -> None:
        """Schemas not in the managed set must be excluded."""
        result = include_name(
            name="pg_catalog",
            type_="schema",
            parent_names={},
        )
        assert result is False


class TestIncludeNameObjectTypes:
    """REQ-8.7: include_name returns True for table and column object types."""

    def test_table_type_returns_true(self) -> None:
        """Objects of type 'table' are always included."""
        result = include_name(
            name="scrape_queue",
            type_="table",
            parent_names={"schema_name": "sch_infra"},
        )
        assert result is True

    def test_column_type_returns_true(self) -> None:
        """Objects of type 'column' are always included."""
        result = include_name(
            name="id",
            type_="column",
            parent_names={"schema_name": "sch_infra"},
        )
        assert result is True
