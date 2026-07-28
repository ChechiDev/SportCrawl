"""Redesign tbl_competition in sch_shared schema.

Drops the old minimal table and replaces it with a fully-normalised version
that references tbl_comp_type, tbl_gender, tbl_confederations, tbl_flags,
and tbl_countries.

The stats tables (p28a–p31a) hold FKs to tbl_competition.comp_id.  Those
constraints are dropped before the table is dropped and recreated after.

Revision ID: p34a
Revises: p33a
"""

import sqlalchemy as sa
from alembic import op

revision: str = "p34a"
down_revision: str | None = "p33a"
branch_labels = None
depends_on = None

_STATS_FK_COMP = [
    ("tbl_player_std_stats", "fk_player_std_stats_fk_comp"),
    ("tbl_player_shooting_stats", "fk_player_shooting_stats_fk_comp"),
    ("tbl_player_playing_time_stats", "fk_player_playing_time_stats_fk_comp"),
    ("tbl_player_misc_stats", "fk_player_misc_stats_fk_comp"),
]


def upgrade() -> None:
    for table_name, _ in _STATS_FK_COMP:
        op.execute(
            sa.text(f"TRUNCATE sch_football.{table_name} CASCADE")
        )

    for table_name, constraint_name in _STATS_FK_COMP:
        op.drop_constraint(
            constraint_name,
            table_name,
            schema="sch_football",
            type_="foreignkey",
        )

    op.execute(sa.text("UPDATE sch_shared.tbl_teams SET fk_comp = NULL"))

    op.drop_constraint(
        "fk_tbl_teams_comp",
        "tbl_teams",
        schema="sch_shared",
        type_="foreignkey",
    )

    op.drop_table("tbl_competition", schema="sch_shared")

    op.create_table(
        "tbl_competition",
        sa.Column("comp_id", sa.Integer(), nullable=False, autoincrement=False),
        sa.Column("comp_name", sa.String(200), nullable=False),
        sa.Column("fk_comp_type", sa.Integer(), nullable=False),
        sa.Column("fk_gender", sa.String(1), nullable=False),
        sa.Column("fk_conf", sa.Integer(), nullable=True),
        sa.Column("fk_flag", sa.String(3), nullable=True),
        sa.Column("fk_country", sa.String(10), nullable=True),
        sa.Column("first_season", sa.SmallInteger(), nullable=True),
        sa.Column("last_season", sa.SmallInteger(), nullable=True),
        sa.Column("comp_url", sa.String(500), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("comp_id", name="pk_tbl_competition"),
        sa.ForeignKeyConstraint(
            ["fk_comp_type"],
            ["sch_shared.tbl_comp_type.comp_type_id"],
            name="fk_tbl_competition_fk_comp_type",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["fk_gender"],
            ["sch_shared.tbl_gender.gender"],
            name="fk_tbl_competition_fk_gender",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["fk_conf"],
            ["sch_shared.tbl_confederations.conf_id"],
            name="fk_tbl_competition_fk_conf",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["fk_flag"],
            ["sch_shared.tbl_flags.flag_id"],
            name="fk_tbl_competition_fk_flag",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["fk_country"],
            ["sch_shared.tbl_countries.country_id"],
            name="fk_tbl_competition_fk_country",
            ondelete="SET NULL",
        ),
        schema="sch_shared",
    )

    op.create_index(
        "ix_tbl_competition_fk_comp_type",
        "tbl_competition",
        ["fk_comp_type"],
        schema="sch_shared",
    )

    op.create_foreign_key(
        "fk_tbl_teams_comp",
        "tbl_teams",
        "tbl_competition",
        ["fk_comp"],
        ["comp_id"],
        source_schema="sch_shared",
        referent_schema="sch_shared",
        ondelete="RESTRICT",
    )

    op.create_index(
        "ix_tbl_competition_fk_gender",
        "tbl_competition",
        ["fk_gender"],
        schema="sch_shared",
    )

    for table_name, constraint_name in _STATS_FK_COMP:
        op.create_foreign_key(
            constraint_name,
            table_name,
            "tbl_competition",
            ["fk_comp"],
            ["comp_id"],
            source_schema="sch_football",
            referent_schema="sch_shared",
            ondelete="RESTRICT",
        )


def downgrade() -> None:
    for table_name, constraint_name in _STATS_FK_COMP:
        op.drop_constraint(
            constraint_name,
            table_name,
            schema="sch_football",
            type_="foreignkey",
        )

    op.drop_index(
        "ix_tbl_competition_fk_gender",
        table_name="tbl_competition",
        schema="sch_shared",
    )
    op.drop_index(
        "ix_tbl_competition_fk_comp_type",
        table_name="tbl_competition",
        schema="sch_shared",
    )
    op.drop_constraint(
        "fk_tbl_teams_comp",
        "tbl_teams",
        schema="sch_shared",
        type_="foreignkey",
    )

    op.drop_table("tbl_competition", schema="sch_shared")

    op.create_table(
        "tbl_competition",
        sa.Column("comp_id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("comp_name", sa.String(200), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("comp_id", name="pk_tbl_competition"),
        sa.UniqueConstraint("comp_name", name="uq_tbl_competition_comp_name"),
        schema="sch_shared",
    )

    op.create_foreign_key(
        "fk_tbl_teams_comp",
        "tbl_teams",
        "tbl_competition",
        ["fk_comp"],
        ["comp_id"],
        source_schema="sch_shared",
        referent_schema="sch_shared",
    )

    for table_name, constraint_name in _STATS_FK_COMP:
        op.create_foreign_key(
            constraint_name,
            table_name,
            "tbl_competition",
            ["fk_comp"],
            ["comp_id"],
            source_schema="sch_football",
            referent_schema="sch_shared",
            ondelete="RESTRICT",
        )
