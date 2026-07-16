"""p11b_scrape_queue_locked_at

Revision ID: p11b
Revises: p11a
Create Date: 2026-07-12

Adds locked_at TIMESTAMPTZ NULL to sch_infra.scrape_queue.

locked_at is set when a row transitions to IN_PROGRESS and cleared to NULL
when it reaches DONE or FAILED.  recover_stale() uses it to identify rows
stuck in IN_PROGRESS beyond the configured TTL and reset them to PENDING.

This column is kept in a separate migration from the player tables (p11a)
so that the scrape_queue schema change can be rolled back independently.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import TIMESTAMP

revision: str = "p11b"
down_revision: str | Sequence[str] | None = "p11a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "scrape_queue",
        sa.Column("locked_at", TIMESTAMP(timezone=True), nullable=True),
        schema="sch_infra",
    )


def downgrade() -> None:
    op.drop_column("scrape_queue", "locked_at", schema="sch_infra")
