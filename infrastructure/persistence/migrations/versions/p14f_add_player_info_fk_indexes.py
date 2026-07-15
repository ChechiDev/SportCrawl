"""Add indexes on FK columns in tbl_player_info

Revision ID: p14f
Revises: p14e
Create Date: 2026-07-15
"""

from collections.abc import Sequence

from alembic import op

revision: str = "p14f"
down_revision: str | Sequence[str] | None = "p14e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_player_info_fk_national_team",
        "tbl_player_info",
        ["fk_national_team"],
        schema="sch_shared",
    )
    op.create_index(
        "ix_player_info_fk_ply_pos_1",
        "tbl_player_info",
        ["fk_ply_pos_1"],
        schema="sch_shared",
    )
    op.create_index(
        "ix_player_info_fk_ply_pos_2",
        "tbl_player_info",
        ["fk_ply_pos_2"],
        schema="sch_shared",
    )
    op.create_index(
        "ix_player_info_fk_ply_pos_3",
        "tbl_player_info",
        ["fk_ply_pos_3"],
        schema="sch_shared",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_player_info_fk_ply_pos_3", table_name="tbl_player_info", schema="sch_shared"
    )
    op.drop_index(
        "ix_player_info_fk_ply_pos_2", table_name="tbl_player_info", schema="sch_shared"
    )
    op.drop_index(
        "ix_player_info_fk_ply_pos_1", table_name="tbl_player_info", schema="sch_shared"
    )
    op.drop_index(
        "ix_player_info_fk_national_team",
        table_name="tbl_player_info",
        schema="sch_shared",
    )
