"""Create updated_at and scrape-due triggers in sch_fbref_backend.

Revision ID: p41a
Revises: p40a
"""

import sqlalchemy as sa
from alembic import op

revision: str = "p41a"
down_revision: str | None = "p40a"
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
    # --- fn_set_updated_at ---
    op.execute(sa.text(f"""
        CREATE OR REPLACE FUNCTION {_SCHEMA}.fn_set_updated_at()
        RETURNS TRIGGER LANGUAGE plpgsql AS $$
        BEGIN
            NEW.updated_at := now();
            RETURN NEW;
        END;
        $$
    """))

    # --- fn_notify_scrape_due ---
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

    # --- attach triggers to each table ---
    for table in _TABLES:
        short = table.removeprefix("tbl_")

        # BEFORE UPDATE → set updated_at
        op.execute(sa.text(f"""
            CREATE TRIGGER trg_{short}_updated_at
            BEFORE UPDATE ON {_SCHEMA}.{table}
            FOR EACH ROW EXECUTE FUNCTION {_SCHEMA}.fn_set_updated_at()
        """))

        # AFTER INSERT OR UPDATE OF next_scrape_at → pg_notify
        op.execute(sa.text(f"""
            CREATE TRIGGER trg_{short}_notify
            AFTER INSERT OR UPDATE OF next_scrape_at ON {_SCHEMA}.{table}
            FOR EACH ROW EXECUTE FUNCTION {_SCHEMA}.fn_notify_scrape_due()
        """))


def downgrade() -> None:
    for table in reversed(_TABLES):
        short = table.removeprefix("tbl_")
        op.execute(sa.text(
            f"DROP TRIGGER IF EXISTS trg_{short}_notify ON {_SCHEMA}.{table}"
        ))
        op.execute(sa.text(
            f"DROP TRIGGER IF EXISTS trg_{short}_updated_at ON {_SCHEMA}.{table}"
        ))

    op.execute(sa.text(
        f"DROP FUNCTION IF EXISTS {_SCHEMA}.fn_notify_scrape_due()"
    ))
    op.execute(sa.text(
        f"DROP FUNCTION IF EXISTS {_SCHEMA}.fn_set_updated_at()"
    ))
