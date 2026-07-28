"""Drop country_url column from tbl_countries.

URL is now stored in sch_fbref_backend.tbl_country_urls.

Revision ID: p47a
Revises: p46a
"""

import sqlalchemy as sa
from alembic import op

revision: str = "p47a"
down_revision: str | None = "p46a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(
        "ALTER TABLE sch_fbref_shared.tbl_countries DROP COLUMN country_url"
    ))


def downgrade() -> None:
    op.execute(sa.text(
        "ALTER TABLE sch_fbref_shared.tbl_countries"
        " ADD COLUMN country_url VARCHAR(255) NOT NULL DEFAULT ''"
    ))
