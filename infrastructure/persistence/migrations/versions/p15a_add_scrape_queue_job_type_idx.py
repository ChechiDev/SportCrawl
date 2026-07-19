"""Add partial index on scrape_queue (job_type, id) WHERE status = 'PENDING'.

Revision ID: p15a
Revises: p14m
"""

from collections.abc import Sequence

from alembic import op

revision: str = "p15a"
down_revision: str | None = "p14m"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX ix_scrape_queue_pending_job_type "
        "ON sch_infra.scrape_queue (job_type, id) "
        "WHERE status = 'PENDING'"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS sch_infra.ix_scrape_queue_pending_job_type")
