"""p10b_refactor_country_pk

Revision ID: p10b_refactor_country_pk
Revises: p10a_create_country_tables
Create Date: 2026-07-12

Refactors tbl_countries to use country_id (VARCHAR) as the primary key,
replacing the UUID id column. Updates tbl_flags.fk_country accordingly.

Both tables may contain live data, so the migration migrates fk_country values
via a temporary column rather than a direct USING cast (UUID → VARCHAR(10) would
truncate the 36-char UUID representation).

Steps (upgrade):
  1.  Drop FK constraint on tbl_flags.fk_country
  2.  Add temporary column tbl_flags.fk_country_new VARCHAR(10)
  3.  Populate fk_country_new from tbl_countries.country_id via the UUID join
  4.  Make fk_country_new NOT NULL (asserts every flag has a matching country)
  5.  Drop unique constraint uq_flags_fk_country on the old fk_country column
  6.  Drop index ix_flags_flag_id (recreated at end to avoid name conflict)
  7.  Drop old UUID fk_country column
  8.  Rename fk_country_new → fk_country
  9.  Re-add unique constraint and index on fk_country
  10. Drop unique constraint uq_countries_country_id
  11. Drop PK tbl_countries_pkey (was on id)
  12. Drop UUID id column from tbl_countries
  13. Add PK constraint on tbl_countries.country_id
  14. Re-add FK constraint on tbl_flags.fk_country → tbl_countries.country_id
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "p10b_refactor_country_pk"
down_revision: str | Sequence[str] | None = "p10a_create_country_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Drop FK constraint on tbl_flags.fk_country
    op.drop_constraint(
        "tbl_flags_fk_country_fkey",
        "tbl_flags",
        schema="sch_shared",
        type_="foreignkey",
    )

    # 2. Add temporary column to hold the new VARCHAR country_id value
    op.add_column(
        "tbl_flags",
        sa.Column("fk_country_new", sa.String(10), nullable=True),
        schema="sch_shared",
    )

    # 3. Populate from tbl_countries.country_id via the UUID join
    op.execute(
        """
        UPDATE sch_shared.tbl_flags f
        SET fk_country_new = c.country_id
        FROM sch_shared.tbl_countries c
        WHERE c.id = f.fk_country
        """
    )

    # 4. Assert every flag has a matching country and make NOT NULL
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM sch_shared.tbl_flags WHERE fk_country_new IS NULL
            ) THEN
                RAISE EXCEPTION
                    'p10b: tbl_flags rows exist with no matching tbl_countries.id';
            END IF;
        END;
        $$
        """
    )
    op.alter_column(
        "tbl_flags",
        "fk_country_new",
        nullable=False,
        schema="sch_shared",
    )

    # 5. Drop unique constraint on old fk_country
    op.drop_constraint(
        "uq_flags_fk_country",
        "tbl_flags",
        schema="sch_shared",
        type_="unique",
    )

    # 6. Drop index on flag_id (will be recreated after column rename)
    op.drop_index("ix_flags_flag_id", table_name="tbl_flags", schema="sch_shared")

    # 7. Drop old UUID fk_country column
    op.drop_column("tbl_flags", "fk_country", schema="sch_shared")

    # 8. Rename fk_country_new → fk_country
    op.alter_column(
        "tbl_flags",
        "fk_country_new",
        new_column_name="fk_country",
        schema="sch_shared",
    )

    # 9. Re-add unique constraint and index on new fk_country
    op.create_unique_constraint(
        "uq_flags_fk_country",
        "tbl_flags",
        ["fk_country"],
        schema="sch_shared",
    )
    op.create_index("ix_flags_flag_id", "tbl_flags", ["flag_id"], schema="sch_shared")

    # 10. Drop unique constraint on tbl_countries.country_id
    op.drop_constraint(
        "uq_countries_country_id",
        "tbl_countries",
        schema="sch_shared",
        type_="unique",
    )

    # 11. Drop existing PK constraint (was on id)
    op.drop_constraint(
        "tbl_countries_pkey",
        "tbl_countries",
        schema="sch_shared",
        type_="primary",
    )

    # 12. Drop UUID id column from tbl_countries
    op.drop_column("tbl_countries", "id", schema="sch_shared")

    # 13. Add PK constraint on country_id
    op.create_primary_key(
        "tbl_countries_pkey",
        "tbl_countries",
        ["country_id"],
        schema="sch_shared",
    )

    # 14. Re-add FK constraint on tbl_flags.fk_country → tbl_countries.country_id
    op.create_foreign_key(
        "tbl_flags_fk_country_fkey",
        "tbl_flags",
        "tbl_countries",
        ["fk_country"],
        ["country_id"],
        source_schema="sch_shared",
        referent_schema="sch_shared",
    )


def downgrade() -> None:
    # 1. Drop FK constraint on tbl_flags.fk_country
    op.drop_constraint(
        "tbl_flags_fk_country_fkey",
        "tbl_flags",
        schema="sch_shared",
        type_="foreignkey",
    )

    # 2. Drop PK on country_id
    op.drop_constraint(
        "tbl_countries_pkey",
        "tbl_countries",
        schema="sch_shared",
        type_="primary",
    )

    # 3. Re-add UUID id column with server default
    op.add_column(
        "tbl_countries",
        sa.Column(
            "id",
            UUID(as_uuid=False),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        schema="sch_shared",
    )

    # 4. Restore PK on id
    op.create_primary_key(
        "tbl_countries_pkey",
        "tbl_countries",
        ["id"],
        schema="sch_shared",
    )

    # 5. Re-add unique constraint on country_id
    op.create_unique_constraint(
        "uq_countries_country_id",
        "tbl_countries",
        ["country_id"],
        schema="sch_shared",
    )

    # 6. Add temporary UUID column to tbl_flags
    op.add_column(
        "tbl_flags",
        sa.Column("fk_country_old", UUID(as_uuid=False), nullable=True),
        schema="sch_shared",
    )

    # 7. Populate fk_country_old from tbl_countries.id via country_id join
    op.execute(
        """
        UPDATE sch_shared.tbl_flags f
        SET fk_country_old = c.id
        FROM sch_shared.tbl_countries c
        WHERE c.country_id = f.fk_country
        """
    )

    # 8. Make NOT NULL
    op.alter_column(
        "tbl_flags",
        "fk_country_old",
        nullable=False,
        schema="sch_shared",
    )

    # 9. Drop unique constraint on current fk_country
    op.drop_constraint(
        "uq_flags_fk_country",
        "tbl_flags",
        schema="sch_shared",
        type_="unique",
    )

    # 10. Drop index
    op.drop_index("ix_flags_flag_id", table_name="tbl_flags", schema="sch_shared")

    # 11. Drop current VARCHAR fk_country column
    op.drop_column("tbl_flags", "fk_country", schema="sch_shared")

    # 12. Rename fk_country_old → fk_country
    op.alter_column(
        "tbl_flags",
        "fk_country_old",
        new_column_name="fk_country",
        schema="sch_shared",
    )

    # 13. Re-add unique constraint and index on restored fk_country
    op.create_unique_constraint(
        "uq_flags_fk_country",
        "tbl_flags",
        ["fk_country"],
        schema="sch_shared",
    )
    op.create_index("ix_flags_flag_id", "tbl_flags", ["flag_id"], schema="sch_shared")

    # 14. Re-add FK pointing back to tbl_countries.id
    op.create_foreign_key(
        "tbl_flags_fk_country_fkey",
        "tbl_flags",
        "tbl_countries",
        ["fk_country"],
        ["id"],
        source_schema="sch_shared",
        referent_schema="sch_shared",
    )
