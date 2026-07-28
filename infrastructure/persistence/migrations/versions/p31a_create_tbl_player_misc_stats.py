"""Create tbl_player_misc_stats in sch_football schema.

Stores per-season miscellaneous statistics (cards, fouls, offsides, crosses, etc.)
for each player per competition and team.

Revision ID: p31a
Revises: p30a
"""

import sqlalchemy as sa
from alembic import op

revision: str = "p31a"
down_revision: str | None = "p30a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tbl_player_misc_stats",
        sa.Column("player_id", sa.String(20), nullable=False),
        sa.Column("season", sa.SmallInteger(), nullable=False),
        sa.Column("fk_team", sa.String(8), nullable=False),
        sa.Column("fk_country", sa.String(10), nullable=True),
        sa.Column("fk_comp", sa.Integer(), nullable=False),
        sa.Column(
            "min_per_90",
            sa.Numeric(6, 2),
            nullable=False,
            server_default=sa.text("0.00"),
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
            "yellow_red_cards",
            sa.SmallInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "fouls", sa.SmallInteger(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "fouled", sa.SmallInteger(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "offsides", sa.SmallInteger(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "crosses", sa.SmallInteger(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "interceptions",
            sa.SmallInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "tackles_won",
            sa.SmallInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "pk_won", sa.SmallInteger(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "pk_conceded",
            sa.SmallInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "own_goals",
            sa.SmallInteger(),
            nullable=False,
            server_default=sa.text("0"),
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
            name="pk_tbl_player_misc_stats",
        ),
        sa.ForeignKeyConstraint(
            ["player_id"],
            ["sch_shared.tbl_players.player_id"],
            name="fk_player_misc_stats_player_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["fk_team"],
            ["sch_shared.tbl_teams.team_id"],
            name="fk_player_misc_stats_fk_team",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["fk_country"],
            ["sch_shared.tbl_countries.country_id"],
            name="fk_player_misc_stats_fk_country",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["fk_comp"],
            ["sch_shared.tbl_competition.comp_id"],
            name="fk_player_misc_stats_fk_comp",
            ondelete="RESTRICT",
        ),
        schema="sch_football",
    )

    op.create_index(
        "ix_tbl_player_misc_stats_season",
        "tbl_player_misc_stats",
        ["season"],
        schema="sch_football",
    )
    op.create_index(
        "ix_tbl_player_misc_stats_fk_team",
        "tbl_player_misc_stats",
        ["fk_team"],
        schema="sch_football",
    )
    op.create_index(
        "ix_tbl_player_misc_stats_fk_comp",
        "tbl_player_misc_stats",
        ["fk_comp"],
        schema="sch_football",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_tbl_player_misc_stats_fk_comp",
        table_name="tbl_player_misc_stats",
        schema="sch_football",
    )
    op.drop_index(
        "ix_tbl_player_misc_stats_fk_team",
        table_name="tbl_player_misc_stats",
        schema="sch_football",
    )
    op.drop_index(
        "ix_tbl_player_misc_stats_season",
        table_name="tbl_player_misc_stats",
        schema="sch_football",
    )
    op.drop_table("tbl_player_misc_stats", schema="sch_football")
