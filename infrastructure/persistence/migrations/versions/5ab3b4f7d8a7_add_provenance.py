"""add_provenance

Revision ID: 5ab3b4f7d8a7
Revises: a3f8c1d29e5b
Create Date: 2026-07-09

Creates the sch_infra.provenance table and its supporting enum type.
provenance is an append-only audit log for completed scrape attempts —
each row is an immutable record of one scrape outcome.

Order:
  1. CREATE TYPE sch_infra.provenanceoutcome (idempotent via DO $$ guard)
  2. CREATE TABLE sch_infra.provenance
  3. CREATE INDEX ix_provenance_url_scraped_at (url, scraped_at)
  4. CREATE INDEX ix_provenance_run_id (run_id)

No FK to sch_infra.scrape_queue by design — provenance is intentionally
decoupled so it can record scrapes from any source.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "5ab3b4f7d8a7"
down_revision: str | Sequence[str] | None = "a3f8c1d29e5b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Step 1: Create the enum type idempotently.
    # PostgreSQL has no native IF NOT EXISTS for types; use a DO $$ guard.
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE sch_infra.provenanceoutcome AS ENUM('SUCCESS', 'FAILURE');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
        """
    )

    # Step 2: Create the provenance table.
    # The outcome column uses create_type=False so Alembic does not emit a
    # second CREATE TYPE after the guarded block above.
    op.create_table(
        "provenance",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column(
            "scraped_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "outcome",
            postgresql.ENUM(
                "SUCCESS",
                "FAILURE",
                name="provenanceoutcome",
                schema="sch_infra",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("content_hash", sa.String(128), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="sch_infra",
    )

    # Step 3: Composite index on (url, scraped_at) for freshness queries.
    op.create_index(
        "ix_provenance_url_scraped_at",
        "provenance",
        ["url", "scraped_at"],
        schema="sch_infra",
    )

    # Step 4: Single-column index on run_id for batch grouping queries.
    op.create_index(
        "ix_provenance_run_id",
        "provenance",
        ["run_id"],
        schema="sch_infra",
    )


def downgrade() -> None:
    # Reverse order: indexes → table → enum type.
    op.drop_index(
        "ix_provenance_run_id",
        table_name="provenance",
        schema="sch_infra",
    )
    op.drop_index(
        "ix_provenance_url_scraped_at",
        table_name="provenance",
        schema="sch_infra",
    )
    op.drop_table("provenance", schema="sch_infra")
    op.execute("DROP TYPE IF EXISTS sch_infra.provenanceoutcome")
