"""Drop player_url column from tbl_players.

URL is now stored in sch_fbref_backend.tbl_player_urls.

Revision ID: p48a
Revises: p47a
"""

import sqlalchemy as sa
from alembic import op

revision: str = "p48a"
down_revision: str | None = "p47a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(
        "ALTER TABLE sch_fbref_shared.tbl_players DROP COLUMN player_url"
    ))


def downgrade() -> None:
    op.execute(sa.text(
        "ALTER TABLE sch_fbref_shared.tbl_players"
        " ADD COLUMN player_url VARCHAR(500) NOT NULL DEFAULT ''"
    ))
