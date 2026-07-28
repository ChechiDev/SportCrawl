"""Create sch_fbref_backend schema.

Revision ID: p39a
Revises: p38a
"""

import sqlalchemy as sa
from alembic import op

revision: str = "p39a"
down_revision: str | None = "p38a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text("CREATE SCHEMA sch_fbref_backend"))


def downgrade() -> None:
    op.execute(sa.text("DROP SCHEMA sch_fbref_backend CASCADE"))
