"""Rename PostgreSQL schemas to include fbref namespace prefix.

sch_shared    → sch_fbref_shared
sch_football  → sch_fbref_football
sch_infra     → sch_fbref_infra (via object migration, not RENAME — see note below)

Note: sch_infra cannot be renamed to sch_fbref_infra because env.py pre-creates
sch_fbref_infra as the Alembic version table schema before any migration runs.
All objects (enums, sequences, tables) are moved with SET SCHEMA instead.
Owned sequences must be disowned before moving, then re-owned after table move.

Revision ID: p37a
Revises: p36a
"""

from alembic import op

revision: str = "p37a"
down_revision: str | None = "p36a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER SCHEMA sch_shared RENAME TO sch_fbref_shared")
    op.execute("ALTER SCHEMA sch_football RENAME TO sch_fbref_football")
    op.execute("""
        DO $$
        DECLARE r record;
        BEGIN
            -- Save sequence ownership info before disowning.
            CREATE TEMP TABLE _seq_own AS
            SELECT
                sc.relname AS seq_name,
                t.relname  AS tbl_name,
                a.attname  AS col_name
            FROM pg_class sc
            JOIN pg_namespace sn
                ON sn.oid = sc.relnamespace AND sn.nspname = 'sch_infra'
            JOIN pg_depend d ON d.objid = sc.oid AND d.deptype = 'a'
            JOIN pg_class t ON t.oid = d.refobjid
            JOIN pg_attribute a
                ON a.attrelid = d.refobjid AND a.attnum = d.refobjsubid
            WHERE sc.relkind = 'S';

            -- Disown sequences so they can be moved independently.
            FOR r IN SELECT seq_name FROM _seq_own LOOP
                EXECUTE format(
                    'ALTER SEQUENCE sch_infra.%I OWNED BY NONE', r.seq_name
                );
            END LOOP;

            -- Move enum types.
            FOR r IN
                SELECT typname FROM pg_type t
                JOIN pg_namespace n ON n.oid = t.typnamespace
                WHERE n.nspname = 'sch_infra' AND t.typtype = 'e'
            LOOP
                EXECUTE format(
                    'ALTER TYPE sch_infra.%I SET SCHEMA sch_fbref_infra',
                    r.typname
                );
            END LOOP;

            -- Move sequences.
            FOR r IN
                SELECT sequence_name FROM information_schema.sequences
                WHERE sequence_schema = 'sch_infra'
            LOOP
                EXECUTE format(
                    'ALTER SEQUENCE sch_infra.%I SET SCHEMA sch_fbref_infra',
                    r.sequence_name
                );
            END LOOP;

            -- Move functions (e.g. update_updated_at_column used by triggers).
            FOR r IN
                SELECT proname, pg_get_function_identity_arguments(oid) AS args
                FROM pg_proc
                WHERE pronamespace = (
                    SELECT oid FROM pg_namespace WHERE nspname = 'sch_infra'
                )
            LOOP
                EXECUTE format(
                    'ALTER FUNCTION sch_infra.%I(%s) SET SCHEMA sch_fbref_infra',
                    r.proname, r.args
                );
            END LOOP;

            -- Move tables (skip alembic_version — already in sch_fbref_infra).
            FOR r IN
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'sch_infra' AND table_name != 'alembic_version'
            LOOP
                EXECUTE format(
                    'ALTER TABLE sch_infra.%I SET SCHEMA sch_fbref_infra',
                    r.table_name
                );
            END LOOP;

            -- Re-establish sequence ownership; both seq and table
            -- are now in sch_fbref_infra.
            FOR r IN SELECT * FROM _seq_own LOOP
                EXECUTE format(
                    'ALTER SEQUENCE sch_fbref_infra.%I OWNED BY sch_fbref_infra.%I.%I',
                    r.seq_name, r.tbl_name, r.col_name
                );
            END LOOP;

            DROP TABLE _seq_own;
        END $$;
    """)
    # Only alembic_version remains (legacy from a3f8c1d29e5b); cascade-drop it.
    op.execute("DROP SCHEMA sch_infra CASCADE")


def downgrade() -> None:
    op.execute("ALTER SCHEMA sch_fbref_shared RENAME TO sch_shared")
    op.execute("ALTER SCHEMA sch_fbref_football RENAME TO sch_football")
    op.execute("CREATE SCHEMA sch_infra")
    op.execute("""
        DO $$
        DECLARE r record;
        BEGIN
            CREATE TEMP TABLE _seq_own AS
            SELECT
                sc.relname AS seq_name,
                t.relname  AS tbl_name,
                a.attname  AS col_name
            FROM pg_class sc
            JOIN pg_namespace sn
                ON sn.oid = sc.relnamespace AND sn.nspname = 'sch_fbref_infra'
            JOIN pg_depend d ON d.objid = sc.oid AND d.deptype = 'a'
            JOIN pg_class t ON t.oid = d.refobjid
            JOIN pg_attribute a
                ON a.attrelid = d.refobjid AND a.attnum = d.refobjsubid
            WHERE sc.relkind = 'S';

            FOR r IN SELECT seq_name FROM _seq_own LOOP
                EXECUTE format(
                    'ALTER SEQUENCE sch_fbref_infra.%I OWNED BY NONE',
                    r.seq_name
                );
            END LOOP;

            FOR r IN
                SELECT typname FROM pg_type t
                JOIN pg_namespace n ON n.oid = t.typnamespace
                WHERE n.nspname = 'sch_fbref_infra' AND t.typtype = 'e'
            LOOP
                EXECUTE format(
                    'ALTER TYPE sch_fbref_infra.%I SET SCHEMA sch_infra',
                    r.typname
                );
            END LOOP;

            FOR r IN
                SELECT proname, pg_get_function_identity_arguments(oid) AS args
                FROM pg_proc
                WHERE pronamespace = (
                    SELECT oid FROM pg_namespace WHERE nspname = 'sch_fbref_infra'
                )
            LOOP
                EXECUTE format(
                    'ALTER FUNCTION sch_fbref_infra.%I(%s) SET SCHEMA sch_infra',
                    r.proname, r.args
                );
            END LOOP;

            FOR r IN
                SELECT sequence_name FROM information_schema.sequences
                WHERE sequence_schema = 'sch_fbref_infra'
            LOOP
                EXECUTE format(
                    'ALTER SEQUENCE sch_fbref_infra.%I SET SCHEMA sch_infra',
                    r.sequence_name
                );
            END LOOP;

            FOR r IN
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'sch_fbref_infra'
                  AND table_name != 'alembic_version'
            LOOP
                EXECUTE format(
                    'ALTER TABLE sch_fbref_infra.%I SET SCHEMA sch_infra',
                    r.table_name
                );
            END LOOP;

            FOR r IN SELECT * FROM _seq_own LOOP
                EXECUTE format(
                    'ALTER SEQUENCE sch_infra.%I OWNED BY sch_infra.%I.%I',
                    r.seq_name, r.tbl_name, r.col_name
                );
            END LOOP;

            DROP TABLE _seq_own;
        END $$;
    """)
    # alembic_version remains in sch_fbref_infra — Alembic manages it and needs
    # the schema alive to write the version record after this downgrade completes.
    # Do NOT drop sch_fbref_infra here.
