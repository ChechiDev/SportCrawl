"""Backfill tbl_player_urls.url to absolute URLs (https://fbref.com prefix).

All existing rows that stored relative paths (e.g. /en/players/...) are
updated to include the full origin. Forward-only — downgrade is a no-op
because reverting to relative URLs would break the scheduler.

Revision ID: p44a
Revises: p43a
"""

import sqlalchemy as sa
from alembic import op

revision: str = "p44a"
down_revision: str | None = "p43a"
branch_labels = None
depends_on = None

_SCHEMA = "sch_fbref_backend"
_TABLE = "tbl_player_urls"
_BASE_URL = "https://fbref.com"


def upgrade() -> None:
    op.execute(sa.text(
        f"UPDATE {_SCHEMA}.{_TABLE}"
        f" SET url = '{_BASE_URL}' || url"
        f" WHERE url NOT LIKE 'https://%'"
    ))


def downgrade() -> None:
    pass
