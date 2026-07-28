"""Add fn_notify_all_due() to sch_fbref_backend.

Scans all 5 URL tables for rows where next_scrape_at <= now() and
status = 'PENDING', then emits a pg_notify for each one on the
'fbref_scrape_due' channel. Called by CadenceScheduler every 60 s
as a poll fallback — catches rows that became due while the daemon
was down or that the row-level trigger may have missed.

Revision ID: p43a
Revises: p42a
"""

import sqlalchemy as sa
from alembic import op

revision: str = "p43a"
down_revision: str | None = "p42a"
branch_labels = None
depends_on = None

_SCHEMA = "sch_fbref_backend"

_TABLES = [
    "tbl_player_urls",
    "tbl_team_urls",
    "tbl_competition_urls",
    "tbl_country_urls",
    "tbl_country_squad_urls",
]


def upgrade() -> None:
    selects = "\n    UNION ALL\n    ".join(
        f"""SELECT '{t}' AS tbl, id, url, url_type, priority, next_scrape_at
        FROM {_SCHEMA}.{t}
        WHERE status = 'PENDING' AND next_scrape_at <= now()"""
        for t in _TABLES
    )

    op.execute(sa.text(f"""
        CREATE OR REPLACE FUNCTION {_SCHEMA}.fn_notify_all_due()
        RETURNS void LANGUAGE plpgsql AS $$
        DECLARE
            _r RECORD;
            _payload JSONB;
        BEGIN
            FOR _r IN (
                {selects}
            ) LOOP
                _payload := jsonb_build_object(
                    'table',          _r.tbl,
                    'id',             _r.id,
                    'url',            _r.url,
                    'url_type',       _r.url_type,
                    'priority',       _r.priority,
                    'next_scrape_at', _r.next_scrape_at
                );
                PERFORM pg_notify('fbref_scrape_due', _payload::TEXT);
            END LOOP;
        END;
        $$
    """))


def downgrade() -> None:
    op.execute(sa.text(
        f"DROP FUNCTION IF EXISTS {_SCHEMA}.fn_notify_all_due()"
    ))
