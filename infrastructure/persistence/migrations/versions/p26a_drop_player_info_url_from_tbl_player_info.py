"""Drop player_info_url column from tbl_player_info.

The URL is already stored in tbl_players.player_url — this column was redundant.

Revision ID: p26a
Revises: p25a
"""

import sqlalchemy as sa
from alembic import op

revision: str = "p26a"
down_revision: str | None = "p25a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("tbl_player_info", "player_info_url", schema="sch_shared")


def downgrade() -> None:
    op.add_column(
        "tbl_player_info",
        sa.Column("player_info_url", sa.VARCHAR(500), nullable=True),
        schema="sch_shared",
    )
