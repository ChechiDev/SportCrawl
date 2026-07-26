"""Add players_url column to tbl_countries.

Revision ID: p25a
Revises: p24a
"""

import sqlalchemy as sa
from alembic import op

revision: str = "p25a"
down_revision: str | None = "p24a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tbl_countries",
        sa.Column("players_url", sa.String(500), nullable=True),
        schema="sch_shared",
    )


def downgrade() -> None:
    op.drop_column("tbl_countries", "players_url", schema="sch_shared")
