"""Alter tbl_competition.fk_gender from varchar to integer.

Changes fk_gender column type from character varying(1) (referencing
tbl_gender.gender) to integer (referencing tbl_gender.id).

Revision ID: p35a
Revises: p34a
"""

import sqlalchemy as sa
from alembic import op

revision: str = "p35a"
down_revision: str | None = "p34a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "fk_tbl_competition_fk_gender",
        "tbl_competition",
        schema="sch_shared",
        type_="foreignkey",
    )

    op.execute(
        sa.text(
            """
            ALTER TABLE sch_shared.tbl_competition
            ALTER COLUMN fk_gender TYPE integer
            USING CASE
                WHEN fk_gender = 'M' THEN 1
                WHEN fk_gender = 'F' THEN 2
            END
            """
        )
    )

    op.create_foreign_key(
        "fk_tbl_competition_fk_gender",
        "tbl_competition",
        "tbl_gender",
        ["fk_gender"],
        ["id"],
        source_schema="sch_shared",
        referent_schema="sch_shared",
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_tbl_competition_fk_gender",
        "tbl_competition",
        schema="sch_shared",
        type_="foreignkey",
    )

    op.execute(
        sa.text(
            """
            ALTER TABLE sch_shared.tbl_competition
            ALTER COLUMN fk_gender TYPE character varying(1)
            USING CASE
                WHEN fk_gender = 1 THEN 'M'
                WHEN fk_gender = 2 THEN 'F'
            END
            """
        )
    )

    op.create_foreign_key(
        "fk_tbl_competition_fk_gender",
        "tbl_competition",
        "tbl_gender",
        ["fk_gender"],
        ["gender"],
        source_schema="sch_shared",
        referent_schema="sch_shared",
        ondelete="RESTRICT",
    )
