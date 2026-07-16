"""p10a_create_country_tables

Revision ID: p10a_create_country_tables
Revises: p8c_create_sch_football
Create Date: 2026-07-12

Creates the country-domain tables in sch_shared:
  tbl_confederations — governing bodies (UEFA, AFC, CAF, OFC, CONMEBOL, CONCACAF)
  tbl_gender         — reference lookup: M / F (seeded in upgrade)
  tbl_countries      — FBRef country data, FK → tbl_confederations
  tbl_flags          — country flag metadata, FK → tbl_countries (1:1)

Creation order respects FK dependencies:
  confederations → countries → flags  (gender is independent)

Downgrade drops in reverse FK order.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "p10a_create_country_tables"
down_revision: str | Sequence[str] | None = "p8c_create_sch_football"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tbl_confederations",
        sa.Column("conf_id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("conf_name", sa.String(50), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("conf_name", name="uq_confederations_conf_name"),
        schema="sch_shared",
    )

    op.create_table(
        "tbl_gender",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("gender", sa.String(1), nullable=False),
        sa.UniqueConstraint("gender", name="uq_gender_gender"),
        schema="sch_shared",
    )

    # Seed static gender values
    op.execute("INSERT INTO sch_shared.tbl_gender (gender) VALUES ('M'), ('F')")

    op.create_table(
        "tbl_countries",
        sa.Column(
            "id",
            UUID(as_uuid=False),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("country_id", sa.String(10), nullable=False),
        sa.Column("country_name", sa.String(100), nullable=False),
        sa.Column("country_url", sa.String(255), nullable=False),
        sa.Column(
            "fk_conf",
            sa.Integer,
            sa.ForeignKey("sch_shared.tbl_confederations.conf_id"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("country_id", name="uq_countries_country_id"),
        schema="sch_shared",
    )

    op.create_table(
        "tbl_flags",
        sa.Column(
            "id",
            UUID(as_uuid=False),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("flag_id", sa.String(2), nullable=False),
        sa.Column("flag_url", sa.String(500), nullable=False),
        sa.Column(
            "fk_country",
            UUID(as_uuid=False),
            sa.ForeignKey("sch_shared.tbl_countries.id"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("fk_country", name="uq_flags_fk_country"),
        schema="sch_shared",
    )

    op.create_index("ix_flags_flag_id", "tbl_flags", ["flag_id"], schema="sch_shared")

    op.create_index(
        "ix_countries_fk_conf", "tbl_countries", ["fk_conf"], schema="sch_shared"
    )
    op.create_index(
        "ix_countries_country_name",
        "tbl_countries",
        ["country_name"],
        schema="sch_shared",
    )


def downgrade() -> None:
    op.drop_index("ix_flags_flag_id", table_name="tbl_flags", schema="sch_shared")

    op.drop_index(
        "ix_countries_country_name",
        table_name="tbl_countries",
        schema="sch_shared",
    )
    op.drop_index(
        "ix_countries_fk_conf", table_name="tbl_countries", schema="sch_shared"
    )

    op.drop_table("tbl_flags", schema="sch_shared")
    op.drop_table("tbl_countries", schema="sch_shared")
    op.drop_table("tbl_gender", schema="sch_shared")
    op.drop_table("tbl_confederations", schema="sch_shared")
