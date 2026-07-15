"""p14b_scrape_queue_claim_index

Revision ID: p14b
Revises: p14a
Create Date: 2026-07-15

Adds a composite index on (status, job_type, id) to speed up the
SELECT FOR UPDATE SKIP LOCKED claim query in PlayerInfoQueueRepository.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "p14b"
down_revision = "p14a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_scrape_queue_claim",
        "scrape_queue",
        ["status", "job_type", "id"],
        schema="sch_infra",
    )


def downgrade() -> None:
    op.drop_index("ix_scrape_queue_claim", table_name="scrape_queue", schema="sch_infra")
