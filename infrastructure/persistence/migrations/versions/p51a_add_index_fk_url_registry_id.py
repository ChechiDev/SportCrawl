"""Add partial index on scrape_queue.fk_url_registry_id.

Speeds up the daemon upsert WHERE clause and backend mark_scraped lookups.
CONCURRENTLY requires autocommit — cannot run inside a transaction.

Revision ID: p51a
Revises: p50a
"""

import sqlalchemy as sa
from alembic import op

revision: str = "p51a"
down_revision: str | None = "p50a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execution_options(isolation_level="AUTOCOMMIT")
    conn.execute(sa.text(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_scrape_queue_fk_url_registry_id"
        " ON sch_fbref_infra.scrape_queue (fk_url_registry_id)"
        " WHERE fk_url_registry_id IS NOT NULL"
    ))


def downgrade() -> None:
    op.execute(sa.text(
        "DROP INDEX IF EXISTS sch_fbref_infra.ix_scrape_queue_fk_url_registry_id"
    ))
