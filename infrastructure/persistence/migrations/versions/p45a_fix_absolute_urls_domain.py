"""Backfill domain tables to absolute URLs (https://fbref.com prefix).

Updates tbl_competition.comp_url, tbl_countries.country_url, and
tbl_players.player_url to store full absolute URLs. Rows already
containing an absolute URL are left untouched. Forward-only — downgrade
is a no-op because reverting to relative URLs would break the scheduler.

Revision ID: p45a
Revises: p44a
"""

import sqlalchemy as sa
from alembic import op

revision: str = "p45a"
down_revision: str | None = "p44a"
branch_labels = None
depends_on = None

_BASE_URL = "https://fbref.com"
_SCHEMA = "sch_fbref_shared"


def upgrade() -> None:
    op.execute(sa.text(
        f"UPDATE {_SCHEMA}.tbl_competition"
        f" SET comp_url = '{_BASE_URL}' || comp_url"
        f" WHERE comp_url NOT LIKE 'https://%'"
    ))
    op.execute(sa.text(
        f"UPDATE {_SCHEMA}.tbl_countries"
        f" SET country_url = '{_BASE_URL}' || country_url"
        f" WHERE country_url NOT LIKE 'https://%'"
    ))
    op.execute(sa.text(
        f"UPDATE {_SCHEMA}.tbl_players"
        f" SET player_url = '{_BASE_URL}' || player_url"
        f" WHERE player_url NOT LIKE 'https://%'"
    ))


def downgrade() -> None:
    pass
