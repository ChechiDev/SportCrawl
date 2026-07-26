"""Drop redundant index on tbl_player_queue_ref.queue_id.

The unique constraint uq_player_queue_ref_queue_id already creates an index
on queue_id — the explicit ix_player_queue_ref_queue_id is dead weight.

Revision ID: p27a
Revises: p26a
"""

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
    op.create_index(
        "ix_player_queue_ref_queue_id",
        "tbl_player_queue_ref",
        ["queue_id"],
        schema="sch_infra",
    )
