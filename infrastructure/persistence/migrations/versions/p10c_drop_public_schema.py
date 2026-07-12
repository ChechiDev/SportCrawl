"""p10c_drop_public_schema

Revision ID: p10c_drop_public_schema
Revises: p10b_refactor_country_pk
Create Date: 2026-07-12

Moves alembic_version from the public schema to sch_infra, then drops
the public schema entirely. env.py must already be configured to point
version_table_schema to sch_infra before this migration runs, so that
Alembic writes the new head into sch_infra.alembic_version after the
transaction commits.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "p10c_drop_public_schema"
down_revision: str | Sequence[str] | None = "p10b_refactor_country_pk"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Create alembic_version in sch_infra with the same structure.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS sch_infra.alembic_version (
            version_num VARCHAR(32) NOT NULL
        )
        """
    )

    # 2. Copy version data from public.alembic_version only when it exists.
    # On existing DBs, Alembic tracked in public — we migrate the row over.
    # On fresh DBs (CI/testcontainers), env.py tracked in sch_infra from the
    # start so public.alembic_version was never created; the DO block is a no-op.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name = 'alembic_version'
            ) THEN
                INSERT INTO sch_infra.alembic_version
                SELECT * FROM public.alembic_version
                WHERE NOT EXISTS (
                    SELECT 1 FROM sch_infra.alembic_version
                );
                DROP TABLE public.alembic_version;
            END IF;
        END $$
        """
    )

    # 3. Drop the public schema itself (IF EXISTS covers fresh-DB runs where
    # public was already absent or had no tracked version table).
    op.execute("DROP SCHEMA IF EXISTS public CASCADE")


def downgrade() -> None:
    # 1. Re-create public schema.
    op.execute("CREATE SCHEMA IF NOT EXISTS public")

    # 2. Re-create public.alembic_version.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.alembic_version (
            version_num VARCHAR(32) NOT NULL
        )
        """
    )

    # 3. Copy version data back.
    op.execute(
        """
        INSERT INTO public.alembic_version
        SELECT * FROM sch_infra.alembic_version
        """
    )

    # 4. Drop sch_infra.alembic_version.
    op.execute("DROP TABLE sch_infra.alembic_version")
