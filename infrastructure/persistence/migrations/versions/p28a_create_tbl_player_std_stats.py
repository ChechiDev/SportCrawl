"""Create tbl_player_std_stats in sch_football schema.

Stores per-season standard statistics (goals, assists, minutes, etc.)
for each player per competition and team.

Revision ID: p28a
Revises: p27a
"""

import sqlalchemy as sa
from alembic import op

revision: str = "p28a"
down_revision: str | None = "p27a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tbl_player_std_stats",
        sa.Column("player_id", sa.String(20), nullable=False),
        sa.Column("season", sa.SmallInteger(), nullable=False),
        sa.Column("fk_team", sa.String(8), nullable=False),
        sa.Column("fk_country", sa.String(10), nullable=True),
        sa.Column("fk_comp", sa.Integer(), nullable=False),
        sa.Column(
            "age", sa.SmallInteger(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "matches", sa.SmallInteger(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "starts", sa.SmallInteger(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "minutes", sa.SmallInteger(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "min_per_90",
            sa.Numeric(6, 2),
            nullable=False,
            server_default=sa.text("0.00"),
        ),
        sa.Column(
            "goals", sa.SmallInteger(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "assists", sa.SmallInteger(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "goals_assists",
            sa.SmallInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "goals_pk", sa.SmallInteger(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "pk_scored", sa.SmallInteger(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "pk_att", sa.SmallInteger(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "yellow_cards",
            sa.SmallInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "red_cards",
            sa.SmallInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "goals_p90",
            sa.Numeric(6, 2),
            nullable=False,
            server_default=sa.text("0.00"),
        ),
        sa.Column(
            "assists_p90",
            sa.Numeric(6, 2),
            nullable=False,
            server_default=sa.text("0.00"),
        ),
        sa.Column(
            "goals_assists_p90",
            sa.Numeric(6, 2),
            nullable=False,
            server_default=sa.text("0.00"),
        ),
        sa.Column(
            "goals_pk_p90",
            sa.Numeric(6, 2),
            nullable=False,
            server_default=sa.text("0.00"),
        ),
        sa.Column(
            "goals_assists_pk_p90",
            sa.Numeric(6, 2),
            nullable=False,
            server_default=sa.text("0.00"),
        ),
        sa.Column("team_url", sa.String(500), nullable=True),
        sa.Column("comp_url", sa.String(500), nullable=True),
        sa.Column("match_url", sa.String(500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint(
            "player_id",
            "season",
            "fk_team",
            "fk_comp",
            name="pk_tbl_player_std_stats",
        ),
        sa.ForeignKeyConstraint(
            ["player_id"],
            ["sch_shared.tbl_players.player_id"],
            name="fk_player_std_stats_player_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["fk_team"],
            ["sch_shared.tbl_teams.team_id"],
            name="fk_player_std_stats_fk_team",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["fk_country"],
            ["sch_shared.tbl_countries.country_id"],
            name="fk_player_std_stats_fk_country",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["fk_comp"],
            ["sch_shared.tbl_competition.comp_id"],
            name="fk_player_std_stats_fk_comp",
            ondelete="RESTRICT",
        ),
        schema="sch_football",
    )

    op.create_index(
        "ix_tbl_player_std_stats_season",
        "tbl_player_std_stats",
        ["season"],
        schema="sch_football",
    )
    op.create_index(
        "ix_tbl_player_std_stats_fk_team",
        "tbl_player_std_stats",
        ["fk_team"],
        schema="sch_football",
    )
    op.create_index(
        "ix_tbl_player_std_stats_fk_comp",
        "tbl_player_std_stats",
        ["fk_comp"],
        schema="sch_football",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_tbl_player_std_stats_fk_comp",
        table_name="tbl_player_std_stats",
        schema="sch_football",
    )
    op.drop_index(
        "ix_tbl_player_std_stats_fk_team",
        table_name="tbl_player_std_stats",
        schema="sch_football",
    )
    op.drop_index(
        "ix_tbl_player_std_stats_season",
        table_name="tbl_player_std_stats",
        schema="sch_football",
    )
    op.drop_table("tbl_player_std_stats", schema="sch_football")
