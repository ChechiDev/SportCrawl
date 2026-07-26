"""Drop redundant index on tbl_player_queue_ref.queue_id.

The unique constraint uq_player_queue_ref_queue_id already creates an index
on queue_id — the explicit ix_player_queue_ref_queue_id is dead weight.

Revision ID: p27a
Revises: p26a
"""

import sqlalchemy as sa
from alembic import op

revision: str = "p27a"
down_revision: str | None = "p26a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index(
        "ix_player_queue_ref_queue_id",
        table_name="tbl_player_queue_ref",
        schema="sch_infra",
    )


def downgrade() -> None:
    # Guard: tbl_player_queue_ref may not exist when downgrading past the
    # migration that created it (e.g. full downgrade to p11 in integration tests).
    op.execute(
        sa.text(
            "DO $$ BEGIN "
            "  IF EXISTS ("
            "    SELECT 1 FROM pg_tables"
            "    WHERE schemaname = 'sch_infra'"
            "    AND tablename = 'tbl_player_queue_ref'"
            "  ) THEN "
            "    CREATE INDEX IF NOT EXISTS ix_player_queue_ref_queue_id"
            "    ON sch_infra.tbl_player_queue_ref (queue_id);"
            "  END IF;"
            "END $$"
        )
    )
