"""Add fk_national_team to tbl_player_info

Revision ID: p14c
Revises: p14b
Create Date: 2026-07-15
"""

import sqlalchemy as sa
from alembic import op

revision = "p14c"
down_revision = "p14b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tbl_player_info",
        sa.Column(
            "fk_national_team",
            sa.String(10),
            nullable=True,
        ),
        schema="sch_shared",
    )
    op.create_foreign_key(
        "tbl_player_info_fk_national_team_fkey",
        "tbl_player_info",
        "tbl_countries",
        ["fk_national_team"],
        ["country_id"],
        source_schema="sch_shared",
        referent_schema="sch_shared",
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "tbl_player_info_fk_national_team_fkey",
        "tbl_player_info",
        schema="sch_shared",
        type_="foreignkey",
    )
    op.drop_column("tbl_player_info", "fk_national_team", schema="sch_shared")
