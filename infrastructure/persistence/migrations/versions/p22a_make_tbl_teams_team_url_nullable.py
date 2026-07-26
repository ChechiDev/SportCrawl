"""Make tbl_teams.team_url nullable to support stub rows without URL.

Stub rows inserted by upsert_team_stub store team_id from the player HTML.
When club_url is absent, team_url should be NULL rather than an empty string.

upgrade(): ALTER COLUMN team_url DROP NOT NULL
downgrade(): restore NOT NULL (empty strings are set first to satisfy constraint)

Revision ID: p22a
Revises: p21a
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "p22a"
down_revision = "p21a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text("ALTER TABLE sch_shared.tbl_teams ALTER COLUMN team_url DROP NOT NULL")
    )


def downgrade() -> None:
    op.execute(
        sa.text("UPDATE sch_shared.tbl_teams SET team_url = '' WHERE team_url IS NULL")
    )
    op.execute(
        sa.text("ALTER TABLE sch_shared.tbl_teams ALTER COLUMN team_url SET NOT NULL")
    )
