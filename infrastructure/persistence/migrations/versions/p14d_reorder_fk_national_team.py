"""Reorder fk_national_team to appear after fk_country_birth in tbl_player_info

PostgreSQL does not support ALTER TABLE ... ALTER COLUMN AFTER, so this migration
recreates tbl_player_info with the desired column order using a rename-and-recreate
strategy.

Revision ID: p14d
Revises: p14c
Create Date: 2026-07-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "p14d"
down_revision: str | Sequence[str] | None = "p14c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # PostgreSQL does not support column reordering via ALTER TABLE.
    # Strategy: rename existing table, create new table with correct column order,
    # copy data, drop old table.

    # Step 1: rename existing table and its constraints
    op.execute("ALTER TABLE sch_shared.tbl_player_info RENAME TO tbl_player_info_old")
    op.execute(
        "ALTER TABLE sch_shared.tbl_player_info_old "
        "RENAME CONSTRAINT tbl_player_info_pkey TO tbl_player_info_old_pkey"
    )
    op.execute(
        "ALTER TABLE sch_shared.tbl_player_info_old RENAME CONSTRAINT "
        "tbl_player_info_player_id_fkey TO "
        "tbl_player_info_old_player_id_fkey"
    )
    op.execute(
        "ALTER INDEX sch_shared.ix_player_info_fk_country_birth "
        "RENAME TO ix_player_info_old_fk_country_birth"
    )

    # Step 2: create new table with fk_national_team immediately after fk_country_birth
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
        sa.Column(
            "fk_national_team",
            sa.String(10),
            sa.ForeignKey(
                "sch_shared.tbl_countries.country_id",
                ondelete="SET NULL",
                name="tbl_player_info_fk_national_team_fkey",
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

    # Step 3: copy data from old table
    op.execute(
        """
        INSERT INTO sch_shared.tbl_player_info (
            player_id, fk_country_birth, fk_national_team, city_name,
            player_born, player_height, player_weight,
            fk_ply_pos_1, fk_ply_pos_2, fk_ply_pos_3,
            player_foot, player_wages, player_expires,
            player_info_url, created_at, updated_at
        )
        SELECT
            player_id, fk_country_birth, fk_national_team, city_name,
            player_born, player_height, player_weight,
            fk_ply_pos_1, fk_ply_pos_2, fk_ply_pos_3,
            player_foot, player_wages, player_expires,
            player_info_url, created_at, updated_at
        FROM sch_shared.tbl_player_info_old
        """
    )

    # Step 4: recreate index (dropped with old table)
    op.create_index(
        "ix_player_info_fk_country_birth",
        "tbl_player_info",
        ["fk_country_birth"],
        schema="sch_shared",
    )

    # Step 5: drop old table (cascades will not apply — no dependent FKs expected)
    op.execute("DROP TABLE sch_shared.tbl_player_info_old")


def downgrade() -> None:
    # Reverse: move fk_national_team back to the end (same rename strategy)
    op.execute("ALTER TABLE sch_shared.tbl_player_info RENAME TO tbl_player_info_old")
    op.execute(
        "ALTER TABLE sch_shared.tbl_player_info_old "
        "RENAME CONSTRAINT tbl_player_info_pkey TO tbl_player_info_old_pkey"
    )
    op.execute(
        "ALTER TABLE sch_shared.tbl_player_info_old RENAME CONSTRAINT "
        "tbl_player_info_player_id_fkey TO "
        "tbl_player_info_old_player_id_fkey"
    )
    op.execute(
        "ALTER INDEX sch_shared.ix_player_info_fk_country_birth "
        "RENAME TO ix_player_info_old_fk_country_birth"
    )

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
        sa.Column(
            "fk_national_team",
            sa.String(10),
            sa.ForeignKey(
                "sch_shared.tbl_countries.country_id",
                ondelete="SET NULL",
                name="tbl_player_info_fk_national_team_fkey",
            ),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("player_id", name="tbl_player_info_pkey"),
        sa.ForeignKeyConstraint(
            ["player_id"],
            ["sch_shared.tbl_players.player_id"],
            ondelete="CASCADE",
            name="tbl_player_info_player_id_fkey",
        ),
        schema="sch_shared",
    )

    op.execute(
        """
        INSERT INTO sch_shared.tbl_player_info (
            player_id, fk_country_birth, city_name,
            player_born, player_height, player_weight,
            fk_ply_pos_1, fk_ply_pos_2, fk_ply_pos_3,
            player_foot, player_wages, player_expires,
            player_info_url, created_at, updated_at, fk_national_team
        )
        SELECT
            player_id, fk_country_birth, city_name,
            player_born, player_height, player_weight,
            fk_ply_pos_1, fk_ply_pos_2, fk_ply_pos_3,
            player_foot, player_wages, player_expires,
            player_info_url, created_at, updated_at, fk_national_team
        FROM sch_shared.tbl_player_info_old
        """
    )

    op.create_index(
        "ix_player_info_fk_country_birth",
        "tbl_player_info",
        ["fk_country_birth"],
        schema="sch_shared",
    )

    op.execute("DROP TABLE sch_shared.tbl_player_info_old")
