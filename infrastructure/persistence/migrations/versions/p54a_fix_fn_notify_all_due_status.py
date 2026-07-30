"""Fix fn_notify_all_due to use status = 'ACTIVE' instead of 'PENDING'.

p43a created the function filtering on status = 'PENDING'. Backend URL tables
use status = 'ACTIVE' for rows that are ready to scrape. The mismatch meant
the scheduler never emitted notifications for due URLs.

This migration replaces the function body via CREATE OR REPLACE FUNCTION,
keeping everything else identical to p43a.

Revision ID: p54a
Revises: p53a
"""

import sqlalchemy as sa
from alembic import op

revision: str = "p54a"
down_revision: str | None = "p53a"
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

_COUNTRY_TABLE = "tbl_country_squad_urls"


def _make_function(status: str) -> str:
    selects = "\n    UNION ALL\n    ".join(
        (
            f"""SELECT '{t}' AS tbl, id, url, url_type, priority, next_scrape_at,
            fk_country AS fk_country
            FROM {_SCHEMA}.{t}
            WHERE status = '{status}' AND next_scrape_at <= now()"""
            if t == _COUNTRY_TABLE
            else
            f"""SELECT '{t}' AS tbl, id, url, url_type, priority, next_scrape_at,
            NULL::TEXT AS fk_country
            FROM {_SCHEMA}.{t}
            WHERE status = '{status}' AND next_scrape_at <= now()"""
        )
        for t in _TABLES
    )
    return f"""
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
                    'next_scrape_at', _r.next_scrape_at,
                    'fk_country',     _r.fk_country
                );
                PERFORM pg_notify('fbref_scrape_due', _payload::TEXT);
            END LOOP;
        END;
        $$
    """


def upgrade() -> None:
    op.execute(sa.text(_make_function("ACTIVE")))


def downgrade() -> None:
    op.execute(sa.text(_make_function("PENDING")))
