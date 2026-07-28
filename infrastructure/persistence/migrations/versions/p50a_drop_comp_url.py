"""Drop comp_url column from tbl_competition.

URL is now stored in sch_fbref_backend.tbl_competition_urls.

Revision ID: p50a
Revises: p49a
"""

import sqlalchemy as sa
from alembic import op

revision: str = "p50a"
down_revision: str | None = "p49a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(
        "ALTER TABLE sch_fbref_shared.tbl_competition DROP COLUMN comp_url"
    ))


def downgrade() -> None:
    op.execute(sa.text(
        "ALTER TABLE sch_fbref_shared.tbl_competition"
        " ADD COLUMN comp_url VARCHAR(500) NOT NULL DEFAULT ''"
    ))
