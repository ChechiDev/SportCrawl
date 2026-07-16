"""Add partial index on scrape_queue for recover_stale query

Revision ID: p14g
Revises: p14f
Create Date: 2026-07-16
"""

from collections.abc import Sequence

from alembic import op

revision: str = "p14g"
down_revision: str | Sequence[str] | None = "p14f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_scrape_queue_recover_stale",
        "scrape_queue",
        ["job_type", "locked_at"],
        schema="sch_infra",
        postgresql_where="status = 'IN_PROGRESS'",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_scrape_queue_recover_stale",
        table_name="scrape_queue",
        schema="sch_infra",
    )
