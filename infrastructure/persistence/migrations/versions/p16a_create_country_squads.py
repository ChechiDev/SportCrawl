"""Create sch_shared.tbl_country_squads for club discovery scraping.

Revision ID: p16a
Revises: p15a
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "p16a"
down_revision: str | None = "p15a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tbl_country_squads",
        sa.Column("fk_country", sa.String(10), nullable=False),
        sa.Column("fk_flag", sa.String(2), nullable=True),
        sa.Column("clubs_url", sa.String(500), nullable=False),
        sa.Column("nat_team_men_url", sa.String(500), nullable=True),
        sa.Column("nat_team_women_url", sa.String(500), nullable=True),
        sa.Column("fbref_men_squad_id", sa.String(8), nullable=True),
        sa.Column("fbref_women_squad_id", sa.String(8), nullable=True),
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
            name="fk_country_squads_country",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["fk_flag"],
            ["sch_shared.tbl_flags.flag_id"],
            name="fk_country_squads_flag",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("fk_country"),
        schema="sch_shared",
    )
    op.create_index(
        "ix_tbl_country_squads_fk_flag",
        "tbl_country_squads",
        ["fk_flag"],
        schema="sch_shared",
    )
    op.create_index(
        "ix_tbl_country_squads_men_squad_id",
        "tbl_country_squads",
        ["fbref_men_squad_id"],
        schema="sch_shared",
    )
    op.create_index(
        "ix_tbl_country_squads_women_squad_id",
        "tbl_country_squads",
        ["fbref_women_squad_id"],
        schema="sch_shared",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_tbl_country_squads_women_squad_id",
        table_name="tbl_country_squads",
        schema="sch_shared",
    )
    op.drop_index(
        "ix_tbl_country_squads_men_squad_id",
        table_name="tbl_country_squads",
        schema="sch_shared",
    )
    op.drop_index(
        "ix_tbl_country_squads_fk_flag",
        table_name="tbl_country_squads",
        schema="sch_shared",
    )
    op.drop_table("tbl_country_squads", schema="sch_shared")
