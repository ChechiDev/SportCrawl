"""Create sch_shared.tbl_competition and sch_shared.tbl_teams for team discovery.

Revision ID: p16b
Revises: p16a
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "p16b"
down_revision: str | None = "p16a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # tbl_competition has no FK dependencies — create first
    op.create_table(
        "tbl_competition",
        sa.Column("comp_id", sa.Integer, nullable=False, autoincrement=True),
        sa.Column("comp_name", sa.String(200), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("comp_id", name="pk_tbl_competition"),
        sa.UniqueConstraint("comp_name", name="uq_tbl_competition_comp_name"),
        schema="sch_shared",
    )

    # tbl_teams depends on tbl_countries, tbl_gender, and tbl_competition
    op.create_table(
        "tbl_teams",
        sa.Column("team_id", sa.String(8), nullable=False),
        sa.Column("team_name", sa.String(200), nullable=False),
        sa.Column("fk_country", sa.String(10), nullable=False),
        sa.Column("fk_gender", sa.Integer, nullable=False),
        sa.Column("fk_comp", sa.Integer, nullable=True),
        sa.Column("team_from", sa.Integer, nullable=True),
        sa.Column("team_to", sa.Integer, nullable=True),
        sa.Column("team_url", sa.String(500), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["fk_country"],
            ["sch_shared.tbl_countries.country_id"],
            name="fk_tbl_teams_country",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["fk_gender"],
            ["sch_shared.tbl_gender.id"],
            name="fk_tbl_teams_gender",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["fk_comp"],
            ["sch_shared.tbl_competition.comp_id"],
            name="fk_tbl_teams_comp",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("team_id", name="pk_tbl_teams"),
        schema="sch_shared",
    )

    op.create_index(
        "ix_tbl_teams_fk_country",
        "tbl_teams",
        ["fk_country"],
        schema="sch_shared",
    )
    op.create_index(
        "ix_tbl_teams_fk_gender",
        "tbl_teams",
        ["fk_gender"],
        schema="sch_shared",
    )
    op.create_index(
        "ix_tbl_teams_fk_comp",
        "tbl_teams",
        ["fk_comp"],
        schema="sch_shared",
    )


def downgrade() -> None:
    # Strict reverse: indexes first, then tbl_teams, then tbl_competition
    op.drop_index("ix_tbl_teams_fk_comp", table_name="tbl_teams", schema="sch_shared")
    op.drop_index("ix_tbl_teams_fk_gender", table_name="tbl_teams", schema="sch_shared")
    op.drop_index(
        "ix_tbl_teams_fk_country", table_name="tbl_teams", schema="sch_shared"
    )
    op.drop_table("tbl_teams", schema="sch_shared")
    op.drop_table("tbl_competition", schema="sch_shared")
