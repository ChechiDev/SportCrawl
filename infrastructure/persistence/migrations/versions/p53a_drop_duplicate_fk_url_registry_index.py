"""Drop duplicate non-CONCURRENTLY index on fk_url_registry_id.

p42a created ix_scrape_queue_url_registry on fk_url_registry_id WHERE NOT NULL.
p51a created ix_scrape_queue_fk_url_registry_id on the same column with the same
predicate, using CREATE INDEX CONCURRENTLY (safer for production).

The p42a index is redundant. Drop it to avoid write amplification and planner
confusion.

Revision ID: p53a
Revises: p52a
"""

import sqlalchemy as sa
from alembic import op

revision: str = "p53a"
down_revision: str | None = "p52a"
branch_labels = None
depends_on = None

_SCHEMA = "sch_fbref_infra"
_TABLE = "scrape_queue"
_OLD_INDEX = "ix_scrape_queue_url_registry"
_COLUMN = "fk_url_registry_id"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(sa.text(
            f"DROP INDEX CONCURRENTLY IF EXISTS {_SCHEMA}.{_OLD_INDEX}"
        ))


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(sa.text(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {_OLD_INDEX}"
            f" ON {_SCHEMA}.{_TABLE} ({_COLUMN})"
            f" WHERE {_COLUMN} IS NOT NULL"
        ))
