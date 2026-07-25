"""Add FK constraint tbl_player_info.fk_team → tbl_teams.team_id.

The constraint was dropped in p20a and never re-added because p20a was
already recorded as applied by Alembic when it was rewritten.

upgrade(): nulls dangling fk_team values, adds the FK constraint.
downgrade(): drops the constraint.

Revision ID: p23a
Revises: p22a
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "p23a"
down_revision: str | None = "p22a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE sch_shared.tbl_player_info "
            "SET fk_team = NULL "
            "WHERE fk_team IS NOT NULL "
            "AND fk_team NOT IN (SELECT team_id FROM sch_shared.tbl_teams)"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE sch_shared.tbl_player_info "
            "ADD CONSTRAINT tbl_player_info_fk_team_fkey "
            "FOREIGN KEY (fk_team) "
            "REFERENCES sch_shared.tbl_teams(team_id) "
            "ON DELETE SET NULL"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "ALTER TABLE sch_shared.tbl_player_info "
            "DROP CONSTRAINT IF EXISTS tbl_player_info_fk_team_fkey"
        )
    )
