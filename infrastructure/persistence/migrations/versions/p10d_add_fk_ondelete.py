"""p10d_add_fk_ondelete

Revision ID: p10d_add_fk_ondelete
Revises: p10c_drop_public_schema
Create Date: 2026-07-12

Adds ON DELETE behaviour to two FK constraints introduced in p10a:

  sch_shared.tbl_countries.fk_conf   → ON DELETE SET NULL
    A country may exist without a confederation (e.g. independent territories).
    Deleting a confederation must NOT cascade-delete the countries that belonged
    to it; instead, set their fk_conf to NULL so the row is preserved.

  sch_shared.tbl_flags.fk_country    → ON DELETE CASCADE
    A flag is a dependent attribute of a country — it has no meaningful
    existence without its parent row.  Deleting a country must automatically
    remove the associated flag.

The previous constraints defaulted to ON DELETE RESTRICT (PostgreSQL default),
which is overly strict for the confederation→country relationship and incomplete
for the country→flag relationship.

Strategy: drop the old FK, recreate with the correct ON DELETE clause.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "p10d_add_fk_ondelete"
down_revision: str | Sequence[str] | None = "p10c_drop_public_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- tbl_countries.fk_conf: RESTRICT → SET NULL ---
    op.drop_constraint(
        "tbl_countries_fk_conf_fkey",
        "tbl_countries",
        schema="sch_shared",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "tbl_countries_fk_conf_fkey",
        "tbl_countries",
        "tbl_confederations",
        ["fk_conf"],
        ["conf_id"],
        source_schema="sch_shared",
        referent_schema="sch_shared",
        ondelete="SET NULL",
    )

    # --- tbl_flags.fk_country: RESTRICT → CASCADE ---
    op.drop_constraint(
        "tbl_flags_fk_country_fkey",
        "tbl_flags",
        schema="sch_shared",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "tbl_flags_fk_country_fkey",
        "tbl_flags",
        "tbl_countries",
        ["fk_country"],
        ["country_id"],
        source_schema="sch_shared",
        referent_schema="sch_shared",
        ondelete="CASCADE",
    )


def downgrade() -> None:
    # --- tbl_flags.fk_country: CASCADE → RESTRICT (default) ---
    op.drop_constraint(
        "tbl_flags_fk_country_fkey",
        "tbl_flags",
        schema="sch_shared",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "tbl_flags_fk_country_fkey",
        "tbl_flags",
        "tbl_countries",
        ["fk_country"],
        ["country_id"],
        source_schema="sch_shared",
        referent_schema="sch_shared",
    )

    # --- tbl_countries.fk_conf: SET NULL → RESTRICT (default) ---
    op.drop_constraint(
        "tbl_countries_fk_conf_fkey",
        "tbl_countries",
        schema="sch_shared",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "tbl_countries_fk_conf_fkey",
        "tbl_countries",
        "tbl_confederations",
        ["fk_conf"],
        ["conf_id"],
        source_schema="sch_shared",
        referent_schema="sch_shared",
    )
