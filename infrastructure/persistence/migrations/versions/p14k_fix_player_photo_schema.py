"""Fix sch_shared.tbl_player_photo: make player_photo_url NOT NULL, add updated_at.

Revision ID: p14k
Revises: p14j
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "p14k"
down_revision: str | None = "p14j"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "ALTER TABLE sch_shared.tbl_player_photo "
            "ALTER COLUMN player_photo_url SET NOT NULL"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE sch_shared.tbl_player_photo "
            "ADD COLUMN updated_at TIMESTAMPTZ NULL"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "ALTER TABLE sch_shared.tbl_player_photo "
            "DROP COLUMN updated_at"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE sch_shared.tbl_player_photo "
            "ALTER COLUMN player_photo_url DROP NOT NULL"
        )
    )
