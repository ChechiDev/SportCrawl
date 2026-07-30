"""Add partial covering index on scrape_queue for recover_stale queries.

recover_stale filters: status = 'IN_PROGRESS' AND job_type = ? AND locked_at < ?
A partial index on (job_type, locked_at) WHERE status = 'IN_PROGRESS' lets
PostgreSQL skip all non-IN_PROGRESS rows and satisfy the predicate with an
index-only scan.

Revision ID: p55a
Revises: p54a
"""

import sqlalchemy as sa
from alembic import op

revision: str = "p55a"
down_revision: str | None = "p54a"
branch_labels = None
depends_on = None

_SCHEMA = "sch_fbref_infra"
_TABLE = "scrape_queue"
_INDEX = "ix_scrape_queue_recover_stale"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(sa.text(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {_INDEX}"
            f" ON {_SCHEMA}.{_TABLE} (job_type, locked_at)"
            f" WHERE status = 'IN_PROGRESS'"
        ))


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(sa.text(
            f"DROP INDEX CONCURRENTLY IF EXISTS {_SCHEMA}.{_INDEX}"
        ))
