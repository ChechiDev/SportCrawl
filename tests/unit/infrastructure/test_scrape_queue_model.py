"""Unit tests for the ScrapeQueue ORM model structure.

These tests verify column-level declarations using Python introspection —
no database connection required.
"""

import inspect

from sqlalchemy import Text

from infrastructure.persistence.models.scrape_queue import ScrapeQueue


class TestErrorMessageColumn:
    """REQ-6.4: error_message must be declared as mapped_column(Text(), nullable=True)."""

    def test_error_message_column_type_is_text(self) -> None:
        """Column type must be Text, not a SQLAlchemy-inferred VARCHAR."""
        col = ScrapeQueue.error_message.property.columns[0]
        assert isinstance(col.type, Text), (
            f"Expected Text but got {type(col.type).__name__}. "
            "error_message must be declared with mapped_column(Text(), nullable=True)"
        )

    def test_error_message_column_is_nullable(self) -> None:
        """error_message must be nullable=True per migration 134f2e68682a."""
        col = ScrapeQueue.error_message.property.columns[0]
        assert col.nullable is True


class TestUpdatedAtColumn:
    """REQ-6.3: updated_at must document the DB trigger and must NOT have onupdate."""

    def test_updated_at_has_no_onupdate(self) -> None:
        """ORM must NOT set onupdate — the DB trigger is the authoritative source."""
        col = ScrapeQueue.updated_at.property.columns[0]
        assert col.onupdate is None, (
            "updated_at must not use ORM onupdate. "
            "The trigger trg_scrape_queue_updated_at handles this at the DB level."
        )

    def test_updated_at_source_references_trigger(self) -> None:
        """The source file must contain the trigger name as a comment.

        This guards against the comment being removed in future edits.
        """
        source_file = inspect.getfile(ScrapeQueue)
        with open(source_file, encoding="utf-8") as f:
            source = f.read()

        assert "trg_scrape_queue_updated_at" in source, (
            "scrape_queue.py must contain a comment referencing "
            "trg_scrape_queue_updated_at near the updated_at column."
        )
