"""Widen flag_id to VARCHAR(3) to support UK home nation codes (eng, nir, sct, wls).

Revision ID: p24a
Revises: p23a
"""

from alembic import op

revision: str = "p24a"
down_revision: str | None = "p23a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE sch_shared.tbl_flags ALTER COLUMN flag_id TYPE VARCHAR(3)")


def downgrade() -> None:
    # WARNING: unsafe if 3-char codes exist (eng, nir, sct, wls) — truncates to 2 chars.
    op.execute(
        "ALTER TABLE sch_shared.tbl_flags ALTER COLUMN flag_id TYPE VARCHAR(2)"
        " USING LEFT(flag_id, 2)"
    )
