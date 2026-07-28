"""Backfill backend URL tables to absolute URLs (https://fbref.com prefix).

Updates tbl_competition_urls.url, tbl_country_urls.url, and
tbl_player_urls.url in sch_fbref_backend to store full absolute URLs.
Rows already containing an absolute URL are left untouched.
Forward-only — downgrade is a no-op.

Revision ID: p46a
Revises: p45a
"""

import sqlalchemy as sa
from alembic import op

revision: str = "p46a"
down_revision: str | None = "p45a"
branch_labels = None
depends_on = None

_BASE_URL = "https://fbref.com"
_SCHEMA = "sch_fbref_backend"


def upgrade() -> None:
    op.execute(sa.text(
        f"UPDATE {_SCHEMA}.tbl_competition_urls"
        f" SET url = '{_BASE_URL}' || url"
        f" WHERE url NOT LIKE 'https://%'"
    ))
    op.execute(sa.text(
        f"UPDATE {_SCHEMA}.tbl_country_urls"
        f" SET url = '{_BASE_URL}' || url"
        f" WHERE url NOT LIKE 'https://%'"
    ))
    op.execute(sa.text(
        f"UPDATE {_SCHEMA}.tbl_player_urls"
        f" SET url = '{_BASE_URL}' || url"
        f" WHERE url NOT LIKE 'https://%'"
    ))


def downgrade() -> None:
    pass
