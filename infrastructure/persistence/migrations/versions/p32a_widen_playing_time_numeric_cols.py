"""Widen min_pct and ppm in tbl_player_playing_time_stats from NUMERIC(5,2) to NUMERIC(6,2).

Revision ID: p32a
Revises: p31a
"""

import sqlalchemy as sa
from alembic import op

revision: str = "p32a"
down_revision: str | None = "p31a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "tbl_player_playing_time_stats",
        "min_pct",
        type_=sa.Numeric(6, 2),
        schema="sch_football",
    )
    op.alter_column(
        "tbl_player_playing_time_stats",
        "ppm",
        type_=sa.Numeric(6, 2),
        schema="sch_football",
    )


def downgrade() -> None:
    op.alter_column(
        "tbl_player_playing_time_stats",
        "min_pct",
        type_=sa.Numeric(5, 2),
        schema="sch_football",
    )
    op.alter_column(
        "tbl_player_playing_time_stats",
        "ppm",
        type_=sa.Numeric(5, 2),
        schema="sch_football",
    )
