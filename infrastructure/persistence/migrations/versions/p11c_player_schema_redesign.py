"""p11c_player_schema_redesign

Revision ID: p11c
Revises: p11b
Create Date: 2026-07-13

Redesigns the player and player_positions tables in sch_shared:

  tbl_player_positions — converted from a junction table to a lookup table.
    Old: (fk_player, position_code, sort_order) composite PK
    New: (id_position SERIAL PK, position_code UNIQUE)
    Phase 14 (player info scraper) will populate this table.

  tbl_players — schema changes:
    - Drops display_name column
    - full_name: nullable → NOT NULL (parser always fills it now)
    - Renames fk_country_team → fk_country (column and FK constraint)
    - career_end: nullable → NOT NULL (parser fills missing values with career_start)
    - Positions are NOT stored here; they will be scraped in Phase 14.

Both tables are TRUNCATED CASCADE before structural changes because:
  - Old junction rows are incompatible with the new schema
  - Player data will be re-scraped from scratch
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "p11c"
down_revision: str | Sequence[str] | None = "p11b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Truncate both tables — data will be re-scraped; cascade removes FK dependents
    op.execute("TRUNCATE sch_shared.tbl_player_positions CASCADE")
    op.execute("TRUNCATE sch_shared.tbl_players CASCADE")

    # 2. Drop old junction tbl_player_positions (composite PK with fk_player)
    op.drop_table("tbl_player_positions", schema="sch_shared")

    # 3. Create new tbl_player_positions lookup table
    op.create_table(
        "tbl_player_positions",
        sa.Column("id_position", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("position_code", sa.String(10), nullable=False),
        schema="sch_shared",
    )
    op.create_unique_constraint(
        "uq_tbl_player_positions_position_code",
        "tbl_player_positions",
        ["position_code"],
        schema="sch_shared",
    )

    # 4. Drop and recreate tbl_players with correct column order
    #    and nullable fk_ply_pos_1
    op.execute("DROP TABLE sch_shared.tbl_players CASCADE")
    op.create_table(
        "tbl_players",
        sa.Column("player_id", sa.String(20), primary_key=True),
        sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column(
            "fk_country",
            sa.String(10),
            sa.ForeignKey(
                "sch_shared.tbl_countries.country_id",
                ondelete="SET NULL",
                name="tbl_players_fk_country_fkey",
            ),
            nullable=True,
        ),
        sa.Column("career_start", sa.SmallInteger, nullable=False),
        sa.Column("career_end", sa.SmallInteger, nullable=False),
        sa.Column("player_url", sa.String(500), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        schema="sch_shared",
    )
    op.create_index(
        "ix_players_fk_country",
        "tbl_players",
        ["fk_country"],
        schema="sch_shared",
    )


def downgrade() -> None:
    # NOTE: downgrade truncates all player data (rows will need to be re-scraped).

    # 1. Drop new lookup tbl_player_positions (unique constraint acts as the index)
    op.drop_constraint(
        "uq_tbl_player_positions_position_code",
        "tbl_player_positions",
        schema="sch_shared",
        type_="unique",
    )
    op.drop_table("tbl_player_positions", schema="sch_shared")

    # 2. Drop new tbl_players — CASCADE removes the FK index too
    op.execute("DROP TABLE sch_shared.tbl_players CASCADE")

    # 3. Recreate tbl_players with p11b schema
    op.create_table(
        "tbl_players",
        sa.Column("player_id", sa.String(20), primary_key=True),
        sa.Column("full_name", sa.String(200), nullable=True),
        sa.Column(
            "display_name",
            sa.String(200),
            nullable=False,
            server_default="",
        ),
        sa.Column("career_start", sa.SmallInteger, nullable=False),
        sa.Column("career_end", sa.SmallInteger, nullable=True),
        sa.Column(
            "fk_country_team",
            sa.String(10),
            sa.ForeignKey(
                "sch_shared.tbl_countries.country_id",
                ondelete="SET NULL",
                name="tbl_players_fk_country_team_fkey",
            ),
            nullable=True,
        ),
        sa.Column("player_url", sa.String(500), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        schema="sch_shared",
    )
    op.create_index(
        "ix_players_fk_country_team",
        "tbl_players",
        ["fk_country_team"],
        schema="sch_shared",
    )
    # Remove the server_default from display_name after adding
    # (only needed for ADD COLUMN)
    op.alter_column(
        "tbl_players",
        "display_name",
        server_default=None,
        schema="sch_shared",
    )

    # 4. Recreate old junction tbl_player_positions
    op.create_table(
        "tbl_player_positions",
        sa.Column(
            "fk_player",
            sa.String(20),
            sa.ForeignKey(
                "sch_shared.tbl_players.player_id",
                ondelete="CASCADE",
                name="tbl_player_positions_fk_player_fkey",
            ),
            primary_key=True,
        ),
        sa.Column("position_code", sa.String(10), primary_key=True),
        sa.Column("sort_order", sa.SmallInteger, nullable=False),
        schema="sch_shared",
    )
