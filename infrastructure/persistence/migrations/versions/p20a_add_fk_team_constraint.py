"""Add FK constraint on tbl_player_info.fk_team → tbl_teams.team_id.

Relies on upsert_team_stub (called before upsert_player_info) to insert
a minimal placeholder row in tbl_teams whenever a team_id is referenced
but not yet scraped.

upgrade(): nulls out any dangling fk_team values, then adds the FK.
downgrade(): drops the FK constraint so the column is unconstrained again.

Revision ID: p20a
Revises: p19a
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "p20a"
down_revision: str | None = "p19a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Null out any fk_team values that have no matching tbl_teams row so the
    # new FK constraint can be created without a violation.
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
