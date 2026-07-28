"""Create tbl_comp_type in sch_shared schema.

Revision ID: p33a
Revises: p32a
"""

import sqlalchemy as sa
from alembic import op

revision: str = "p33a"
down_revision: str | None = "p32a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tbl_comp_type",
        sa.Column("comp_type_id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("comp_type_name", sa.String(100), nullable=False),
        sa.PrimaryKeyConstraint("comp_type_id", name="pk_tbl_comp_type"),
        sa.UniqueConstraint("comp_type_name", name="uq_tbl_comp_type_comp_type_name"),
        schema="sch_shared",
    )

    op.execute(
        sa.text(
            """
            INSERT INTO sch_shared.tbl_comp_type (comp_type_name) VALUES
                ('Club International Cup'),
                ('National Team Competition'),
                ('Domestic League - 1st Tier'),
                ('Domestic League - 2nd Tier'),
                ('Domestic Leagues - 3rd Tier'),
                ('National Team Qualification'),
                ('Domestic Cup'),
                ('Domestic Youth League')
            ON CONFLICT DO NOTHING
            """
        )
    )


def downgrade() -> None:
    op.drop_table("tbl_comp_type", schema="sch_shared")
