"""p14a_player_info_schema

Revision ID: p14a
Revises: p11e
Create Date: 2026-07-15

Creates two new tables in sch_shared for Phase 14 (player info scraping):

  tbl_player_info — biographical and contract info per player.
    FK → tbl_players.player_id (CASCADE on delete).
    FK → tbl_countries.country_id for birth country (SET NULL on delete).
    FKs → tbl_player_positions.position_id for up to 3 positions (SET NULL on delete).
    Index on fk_country_birth for filter performance.

  tbl_player_photo — one photo URL per player.
    FK → tbl_players.player_id (CASCADE on delete).

downgrade: drops tbl_player_photo, then tbl_player_info (reverse FK order).
Does NOT touch tbl_players, tbl_player_positions, or scrape_queue.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "p14a"
down_revision: str | Sequence[str] | None = "p11e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Create tbl_player_info
    op.create_table(
        "tbl_player_info",
        sa.Column("player_id", sa.String(20), nullable=False),
        sa.Column(
            "fk_country_birth",
            sa.String(10),
            sa.ForeignKey(
                "sch_shared.tbl_countries.country_id",
                ondelete="SET NULL",
                name="tbl_player_info_fk_country_birth_fkey",
            ),
            nullable=True,
        ),
        sa.Column("city_name", sa.String(150), nullable=True),
        sa.Column("player_born", sa.Date, nullable=True),
        sa.Column("player_height", sa.SmallInteger, nullable=True),
        sa.Column("player_weight", sa.SmallInteger, nullable=True),
        sa.Column(
            "fk_ply_pos_1",
            sa.Integer,
            sa.ForeignKey(
                "sch_shared.tbl_player_positions.position_id",
                ondelete="SET NULL",
                name="tbl_player_info_fk_ply_pos_1_fkey",
            ),
            nullable=True,
        ),
        sa.Column(
            "fk_ply_pos_2",
            sa.Integer,
            sa.ForeignKey(
                "sch_shared.tbl_player_positions.position_id",
                ondelete="SET NULL",
                name="tbl_player_info_fk_ply_pos_2_fkey",
            ),
            nullable=True,
        ),
        sa.Column(
            "fk_ply_pos_3",
            sa.Integer,
            sa.ForeignKey(
                "sch_shared.tbl_player_positions.position_id",
                ondelete="SET NULL",
                name="tbl_player_info_fk_ply_pos_3_fkey",
            ),
            nullable=True,
        ),
        sa.Column("player_foot", sa.String(20), nullable=True),
        sa.Column("player_wages", sa.Integer, nullable=True),
        sa.Column("player_expires", sa.Date, nullable=True),
        sa.Column("player_info_url", sa.String(500), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("player_id", name="tbl_player_info_pkey"),
        sa.ForeignKeyConstraint(
            ["player_id"],
            ["sch_shared.tbl_players.player_id"],
            ondelete="CASCADE",
            name="tbl_player_info_player_id_fkey",
        ),
        schema="sch_shared",
    )
    op.create_index(
        "ix_player_info_fk_country_birth",
        "tbl_player_info",
        ["fk_country_birth"],
        schema="sch_shared",
    )

    # 2. Create tbl_player_photo
    op.create_table(
        "tbl_player_photo",
        sa.Column("player_id", sa.String(20), nullable=False),
        sa.Column("player_photo_url", sa.String(500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("player_id", name="tbl_player_photo_pkey"),
        sa.ForeignKeyConstraint(
            ["player_id"],
            ["sch_shared.tbl_players.player_id"],
            ondelete="CASCADE",
            name="tbl_player_photo_player_id_fkey",
        ),
        schema="sch_shared",
    )


def downgrade() -> None:
    # Drop in reverse order (tbl_player_photo has no dependents on tbl_player_info)
    op.drop_table("tbl_player_photo", schema="sch_shared")
    op.drop_index(
        "ix_player_info_fk_country_birth",
        table_name="tbl_player_info",
        schema="sch_shared",
    )
    op.drop_table("tbl_player_info", schema="sch_shared")
