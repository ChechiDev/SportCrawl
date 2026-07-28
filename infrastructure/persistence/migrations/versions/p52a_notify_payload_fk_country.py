"""Add fk_country to pg_notify payloads for tbl_country_squad_urls rows.

Replaces fn_notify_scrape_due() and fn_notify_all_due() with versions that
include fk_country in the JSON payload. Only tbl_country_squad_urls carries
a meaningful fk_country; all other tables emit null for that field.

Revision ID: p52a
Revises: p51a
"""

import sqlalchemy as sa
from alembic import op

revision: str = "p52a"
down_revision: str | None = "p51a"
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

# tbl_country_squad_urls has a fk_country column; all others do not.
_COUNTRY_TABLE = "tbl_country_squad_urls"


def upgrade() -> None:
    # fn_notify_scrape_due fires per-row via trigger; NEW.fk_country is available
    # only on tbl_country_squad_urls (bound at trigger-attach time via TG_TABLE_NAME).
    op.execute(sa.text(f"""
        CREATE OR REPLACE FUNCTION {_SCHEMA}.fn_notify_scrape_due()
        RETURNS TRIGGER LANGUAGE plpgsql AS $$
        DECLARE
            _payload JSONB;
            _fk_country TEXT;
        BEGIN
            IF (TG_OP = 'INSERT' AND NEW.next_scrape_at <= now())
            OR (TG_OP = 'UPDATE'
                AND NEW.next_scrape_at IS DISTINCT FROM OLD.next_scrape_at
                AND NEW.next_scrape_at <= now())
            THEN
                IF TG_TABLE_NAME = 'tbl_country_squad_urls' THEN
                    _fk_country := NEW.fk_country;
                ELSE
                    _fk_country := NULL;
                END IF;
                _payload := jsonb_build_object(
                    'table',          TG_TABLE_NAME,
                    'id',             NEW.id,
                    'url',            NEW.url,
                    'url_type',       NEW.url_type,
                    'priority',       NEW.priority,
                    'next_scrape_at', NEW.next_scrape_at,
                    'fk_country',     _fk_country
                );
                PERFORM pg_notify('fbref_scrape_due', _payload::TEXT);
            END IF;
            RETURN NEW;
        END;
        $$
    """))

    selects = "\n    UNION ALL\n    ".join(
        (
            f"""SELECT '{t}' AS tbl, id, url, url_type, priority, next_scrape_at,
            fk_country AS fk_country
            FROM {_SCHEMA}.{t}
            WHERE status = 'PENDING' AND next_scrape_at <= now()"""
            if t == _COUNTRY_TABLE
            else
            f"""SELECT '{t}' AS tbl, id, url, url_type, priority, next_scrape_at,
            NULL::TEXT AS fk_country
            FROM {_SCHEMA}.{t}
            WHERE status = 'PENDING' AND next_scrape_at <= now()"""
        )
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
                    'next_scrape_at', _r.next_scrape_at,
                    'fk_country',     _r.fk_country
                );
                PERFORM pg_notify('fbref_scrape_due', _payload::TEXT);
            END LOOP;
        END;
        $$
    """))


def downgrade() -> None:
    # Restore the pre-p52a versions (without fk_country) by re-applying p41a/p43a SQL.
    op.execute(sa.text(f"""
        CREATE OR REPLACE FUNCTION {_SCHEMA}.fn_notify_scrape_due()
        RETURNS TRIGGER LANGUAGE plpgsql AS $$
        DECLARE
            _payload JSONB;
        BEGIN
            IF (TG_OP = 'INSERT' AND NEW.next_scrape_at <= now())
            OR (TG_OP = 'UPDATE'
                AND NEW.next_scrape_at IS DISTINCT FROM OLD.next_scrape_at
                AND NEW.next_scrape_at <= now())
            THEN
                _payload := jsonb_build_object(
                    'table',          TG_TABLE_NAME,
                    'id',             NEW.id,
                    'url',            NEW.url,
                    'url_type',       NEW.url_type,
                    'priority',       NEW.priority,
                    'next_scrape_at', NEW.next_scrape_at
                );
                PERFORM pg_notify('fbref_scrape_due', _payload::TEXT);
            END IF;
            RETURN NEW;
        END;
        $$
    """))

    selects_old = "\n    UNION ALL\n    ".join(
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
                {selects_old}
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
