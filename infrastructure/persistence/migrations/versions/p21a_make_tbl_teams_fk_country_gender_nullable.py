"""Make tbl_teams.fk_country and fk_gender nullable to support stub rows.

Stub rows are inserted by upsert_team_stub before the team is fully scraped,
satisfying the FK constraint on tbl_player_info.fk_team. Once the team is
scraped, the full row replaces the stub via ON CONFLICT DO UPDATE.

upgrade(): alter fk_country and fk_gender to nullable.
downgrade(): restore NOT NULL (nulls must be absent first).

Revision ID: p21a
Revises: p20a
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "p21a"
down_revision: str | None = "p20a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "ALTER TABLE sch_shared.tbl_teams "
            "ALTER COLUMN fk_country DROP NOT NULL"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE sch_shared.tbl_teams "
            "ALTER COLUMN fk_gender DROP NOT NULL"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE sch_shared.tbl_teams "
            "ALTER COLUMN team_name DROP NOT NULL"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "ALTER TABLE sch_shared.tbl_teams "
            "ALTER COLUMN team_name SET NOT NULL"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE sch_shared.tbl_teams "
            "ALTER COLUMN fk_country SET NOT NULL"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE sch_shared.tbl_teams "
            "ALTER COLUMN fk_gender SET NOT NULL"
        )
    )
