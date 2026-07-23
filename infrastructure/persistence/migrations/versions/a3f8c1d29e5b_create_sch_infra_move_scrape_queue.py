"""create_sch_infra_move_scrape_queue

Revision ID: a3f8c1d29e5b
Revises: 134f2e68682a
Create Date: 2026-07-09

Creates the sch_infra schema (infrastructure-level tables shared across all
sports) and moves scrape_queue + its scrapestatus enum type into it.

The scrape_queue table is a cross-sport infrastructure concern, not specific
to football. Keeping it in sch_infra allows future sports to reuse it without
polluting sch_football or any other sport schema.

Note: alembic_version is intentionally left in the public schema to avoid
a mid-transaction self-referential schema move (Alembic holds a live handle
to that table during every migration run).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a3f8c1d29e5b"
down_revision: str | Sequence[str] | None = "134f2e68682a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS sch_infra")

    # Idempotent CREATE TYPE — PostgreSQL has no native IF NOT EXISTS for types.
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE sch_infra.scrapestatus
                AS ENUM('PENDING', 'IN_PROGRESS', 'DONE', 'FAILED');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
        """
    )

    # Drop the server default before the type change — PostgreSQL cannot
    # automatically cast the 'PENDING' text default to the new schema-qualified
    # enum during ALTER COLUMN TYPE.
    op.execute("ALTER TABLE public.scrape_queue ALTER COLUMN status DROP DEFAULT")

    # Migrate the status column to the new schema-qualified enum.
    # Table is still in public at this point — use fully-qualified reference.
    op.execute(
        "ALTER TABLE public.scrape_queue "
        "ALTER COLUMN status TYPE sch_infra.scrapestatus "
        "USING status::text::sch_infra.scrapestatus"
    )

    # Restore the server default using the new schema-qualified enum.
    op.execute(
        "ALTER TABLE public.scrape_queue "
        "ALTER COLUMN status SET DEFAULT 'PENDING'::sch_infra.scrapestatus"
    )

    # Remove the old unqualified (public) enum now that the column no longer
    # references it.
    op.execute("DROP TYPE IF EXISTS public.scrapestatus")

    # Move the table (indexes, constraints, and triggers travel with it).
    op.execute("ALTER TABLE public.scrape_queue SET SCHEMA sch_infra")


def downgrade() -> None:
    # Move the table back to public.
    op.execute("ALTER TABLE sch_infra.scrape_queue SET SCHEMA public")

    # Restore the unqualified public enum (idempotent — mirrors upgrade pattern).
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE public.scrapestatus
                AS ENUM('PENDING', 'IN_PROGRESS', 'DONE', 'FAILED');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
        """
    )

    # Drop the schema-qualified default before reverting the type.
    op.execute("ALTER TABLE public.scrape_queue ALTER COLUMN status DROP DEFAULT")

    # Restore the status column to the public enum.
    # Table is back in public — use fully-qualified reference.
    op.execute(
        "ALTER TABLE public.scrape_queue "
        "ALTER COLUMN status TYPE public.scrapestatus "
        "USING status::text::public.scrapestatus"
    )

    # Restore the server default using the public enum.
    op.execute(
        "ALTER TABLE public.scrape_queue "
        "ALTER COLUMN status SET DEFAULT 'PENDING'::public.scrapestatus"
    )

    # Drop the schema-qualified enum.
    op.execute("DROP TYPE IF EXISTS sch_infra.scrapestatus")

    # RESTRICT is the default but made explicit: fails if the schema is not
    # empty, which is the safe behavior — it prevents silently dropping objects
    # added by later migrations.
    op.execute("DROP SCHEMA IF EXISTS sch_infra RESTRICT")
