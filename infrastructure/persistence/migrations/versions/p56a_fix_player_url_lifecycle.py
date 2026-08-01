"""fix tbl_player_urls scheduling lifecycle: correct partial index and fn_notify_all_due

Revision ID: p56a
Revises: p55a
Create Date: 2026-07-30

Changes:
- Drop ix_player_urls_due (WHERE status = 'ACTIVE' matched nothing; rows start PENDING)
- Recreate as WHERE status IN ('PENDING', 'ACTIVE') to cover initial and recurring rows
- Update fn_notify_all_due() to filter status IN ('PENDING', 'ACTIVE')
"""

import sqlalchemy as sa
from alembic import op

revision: str = "p56a"
down_revision: str | None = "p55a"
branch_labels = None
depends_on = None

_SCHEMA = "sch_fbref_backend"
_INDEX = "ix_player_urls_due"
_TABLE = "tbl_player_urls"

_TABLES = [
    "tbl_player_urls",
    "tbl_team_urls",
    "tbl_competition_urls",
    "tbl_country_urls",
    "tbl_country_squad_urls",
]

_COUNTRY_TABLE = "tbl_country_squad_urls"


def _make_function(status_filter: str) -> str:
    """Build fn_notify_all_due SQL with the given status filter expression."""
    selects = "\n    UNION ALL\n    ".join(
        (
            f"""SELECT '{t}' AS tbl, id, url, url_type, priority, next_scrape_at,
            fk_country AS fk_country
            FROM {_SCHEMA}.{t}
            WHERE {status_filter} AND next_scrape_at <= now()"""
            if t == _COUNTRY_TABLE
            else
            f"""SELECT '{t}' AS tbl, id, url, url_type, priority, next_scrape_at,
            NULL::TEXT AS fk_country
            FROM {_SCHEMA}.{t}
            WHERE {status_filter} AND next_scrape_at <= now()"""
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


_OTHER_DUE_INDEXES = [
    ("ix_team_urls_due", "tbl_team_urls"),
    ("ix_competition_urls_due", "tbl_competition_urls"),
    ("ix_country_urls_due", "tbl_country_urls"),
    ("ix_country_squad_urls_due", "tbl_country_squad_urls"),
]


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(sa.text(
            f"DROP INDEX CONCURRENTLY IF EXISTS {_SCHEMA}.{_INDEX}"
        ))
        op.execute(sa.text(
            f"CREATE INDEX CONCURRENTLY {_INDEX}"
            f" ON {_SCHEMA}.{_TABLE} (priority ASC, next_scrape_at ASC, id ASC)"
            f" WHERE status IN ('PENDING', 'ACTIVE')"
        ))
        for idx_name, tbl_name in _OTHER_DUE_INDEXES:
            op.execute(sa.text(
                f"DROP INDEX CONCURRENTLY IF EXISTS {_SCHEMA}.{idx_name}"
            ))
            op.execute(sa.text(
                f"CREATE INDEX CONCURRENTLY {idx_name}"
                f" ON {_SCHEMA}.{tbl_name} (next_scrape_at ASC, priority ASC)"
                f" WHERE status IN ('PENDING', 'ACTIVE')"
            ))
    op.execute(sa.text(_make_function("status IN ('PENDING', 'ACTIVE')")))


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(sa.text(
            f"DROP INDEX CONCURRENTLY IF EXISTS {_SCHEMA}.{_INDEX}"
        ))
        op.execute(sa.text(
            f"CREATE INDEX CONCURRENTLY {_INDEX}"
            f" ON {_SCHEMA}.{_TABLE} (next_scrape_at, priority)"
            f" WHERE status = 'ACTIVE'"
        ))
        for idx_name, tbl_name in _OTHER_DUE_INDEXES:
            op.execute(sa.text(
                f"DROP INDEX CONCURRENTLY IF EXISTS {_SCHEMA}.{idx_name}"
            ))
            op.execute(sa.text(
                f"CREATE INDEX CONCURRENTLY {idx_name}"
                f" ON {_SCHEMA}.{tbl_name} (next_scrape_at, priority)"
                f" WHERE status = 'ACTIVE'"
            ))
    op.execute(sa.text(_make_function("status = 'ACTIVE'")))
