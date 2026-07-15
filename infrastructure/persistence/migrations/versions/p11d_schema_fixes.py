"""p11d_schema_fixes

Revision ID: p11d
Revises: p11c
Create Date: 2026-07-15

Schema fixes applied after p11c:

  tbl_player_positions (sch_shared) — renames id_position → position_id
    to align with the project-wide convention (column name mirrors FK name).

  scrape_queue (sch_infra) — adds job_type VARCHAR(50) nullable
    to distinguish queue entries by scraping job (e.g. 'player_discovery').
    Existing rows are backfilled to 'player_discovery'.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "p11d"
down_revision: str | Sequence[str] | None = "p11c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Rename id_position → position_id in tbl_player_positions
    op.alter_column(
        "tbl_player_positions",
        "id_position",
        new_column_name="position_id",
        schema="sch_shared",
    )

    # 2. Add job_type column to scrape_queue
    op.add_column(
        "scrape_queue",
        sa.Column("job_type", sa.String(50), nullable=True),
        schema="sch_infra",
    )

    # 3. Backfill existing rows
    op.execute(
        "UPDATE sch_infra.scrape_queue"
        " SET job_type = 'player_discovery' WHERE job_type IS NULL"
    )


def downgrade() -> None:
    # 1. Drop job_type from scrape_queue
    op.drop_column("scrape_queue", "job_type", schema="sch_infra")

    # 2. Rename position_id → id_position in tbl_player_positions
    op.alter_column(
        "tbl_player_positions",
        "position_id",
        new_column_name="id_position",
        schema="sch_shared",
    )
