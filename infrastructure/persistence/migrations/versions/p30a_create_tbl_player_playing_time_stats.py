"""Create tbl_player_playing_time_stats in sch_football schema.

Stores per-season playing time statistics (minutes, starts, subs, on/off, etc.)
for each player per competition and team.

Revision ID: p30a
Revises: p29a
"""

import sqlalchemy as sa
from alembic import op

revision: str = "p30a"
down_revision: str | None = "p29a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tbl_player_playing_time_stats",
        sa.Column("player_id", sa.String(20), nullable=False),
        sa.Column("season", sa.SmallInteger(), nullable=False),
        sa.Column("fk_team", sa.String(8), nullable=False),
        sa.Column("fk_country", sa.String(10), nullable=True),
        sa.Column("fk_comp", sa.Integer(), nullable=False),
        sa.Column(
            "matches", sa.SmallInteger(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "minutes", sa.SmallInteger(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "min_per_match",
            sa.Numeric(6, 2),
            nullable=False,
            server_default=sa.text("0.00"),
        ),
        sa.Column(
            "min_pct",
            sa.Numeric(5, 2),
            nullable=False,
            server_default=sa.text("0.00"),
        ),
        sa.Column(
            "min_per_90",
            sa.Numeric(6, 2),
            nullable=False,
            server_default=sa.text("0.00"),
        ),
        sa.Column(
            "starts", sa.SmallInteger(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "min_per_start",
            sa.Numeric(6, 2),
            nullable=False,
            server_default=sa.text("0.00"),
        ),
        sa.Column(
            "games_complete",
            sa.SmallInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "subs", sa.SmallInteger(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "min_per_sub",
            sa.Numeric(6, 2),
            nullable=False,
            server_default=sa.text("0.00"),
        ),
        sa.Column(
            "unused_sub",
            sa.SmallInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "ppm",
            sa.Numeric(5, 2),
            nullable=False,
            server_default=sa.text("0.00"),
        ),
        sa.Column(
            "on_goals_for",
            sa.SmallInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "on_goals_against",
            sa.SmallInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "plus_minus",
            sa.SmallInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "plus_minus_per90",
            sa.Numeric(6, 2),
            nullable=False,
            server_default=sa.text("0.00"),
        ),
        sa.Column(
            "on_off",
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
            name="pk_tbl_player_playing_time_stats",
        ),
        sa.ForeignKeyConstraint(
            ["player_id"],
            ["sch_shared.tbl_players.player_id"],
            name="fk_player_playing_time_stats_player_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["fk_team"],
            ["sch_shared.tbl_teams.team_id"],
            name="fk_player_playing_time_stats_fk_team",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["fk_country"],
            ["sch_shared.tbl_countries.country_id"],
            name="fk_player_playing_time_stats_fk_country",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["fk_comp"],
            ["sch_shared.tbl_competition.comp_id"],
            name="fk_player_playing_time_stats_fk_comp",
            ondelete="RESTRICT",
        ),
        schema="sch_football",
    )

    op.create_index(
        "ix_tbl_player_playing_time_stats_season",
        "tbl_player_playing_time_stats",
        ["season"],
        schema="sch_football",
    )
    op.create_index(
        "ix_tbl_player_playing_time_stats_fk_team",
        "tbl_player_playing_time_stats",
        ["fk_team"],
        schema="sch_football",
    )
    op.create_index(
        "ix_tbl_player_playing_time_stats_fk_comp",
        "tbl_player_playing_time_stats",
        ["fk_comp"],
        schema="sch_football",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_tbl_player_playing_time_stats_fk_comp",
        table_name="tbl_player_playing_time_stats",
        schema="sch_football",
    )
    op.drop_index(
        "ix_tbl_player_playing_time_stats_fk_team",
        table_name="tbl_player_playing_time_stats",
        schema="sch_football",
    )
    op.drop_index(
        "ix_tbl_player_playing_time_stats_season",
        table_name="tbl_player_playing_time_stats",
        schema="sch_football",
    )
    op.drop_table("tbl_player_playing_time_stats", schema="sch_football")
