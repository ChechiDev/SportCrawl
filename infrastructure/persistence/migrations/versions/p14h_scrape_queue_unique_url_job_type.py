"""Change scrape_queue unique constraint from (url) to (url, job_type).

This allows the same URL to be scraped for different job types
(e.g. player_discovery and player_info).

Revision ID: p14h
Revises: p14g
"""

from collections.abc import Sequence

from alembic import op

revision: str = "p14h"
down_revision: str | Sequence[str] | None = "p14g"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_scrape_queue_url", "scrape_queue", schema="sch_infra"
    )
    op.create_unique_constraint(
        "uq_scrape_queue_url_job_type",
        "scrape_queue",
        ["url", "job_type"],
        schema="sch_infra",
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_scrape_queue_url_job_type", "scrape_queue", schema="sch_infra"
    )
    op.create_unique_constraint(
        "uq_scrape_queue_url", "scrape_queue", ["url"], schema="sch_infra"
    )
