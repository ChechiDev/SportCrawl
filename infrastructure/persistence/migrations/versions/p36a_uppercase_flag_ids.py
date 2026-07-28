"""Uppercase all flag_id values across tbl_flags, tbl_country_squads,
and tbl_competition.

Scrapers now emit UPPER-case flag codes. This migration normalises all existing
rows so FK references remain consistent after the scraper change.

Revision ID: p36a
Revises: p35a
"""

from alembic import op

revision: str = "p36a"
down_revision: str | None = "p35a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "fk_country_squads_flag",
        "tbl_country_squads",
        schema="sch_shared",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_tbl_competition_fk_flag",
        "tbl_competition",
        schema="sch_shared",
        type_="foreignkey",
    )

    op.execute(
        "UPDATE sch_shared.tbl_country_squads"
        " SET fk_flag = UPPER(fk_flag) WHERE fk_flag IS NOT NULL"
    )
    op.execute(
        "UPDATE sch_shared.tbl_competition"
        " SET fk_flag = UPPER(fk_flag) WHERE fk_flag IS NOT NULL"
    )
    op.execute("UPDATE sch_shared.tbl_flags SET flag_id = UPPER(flag_id)")

    op.create_foreign_key(
        "fk_country_squads_flag",
        "tbl_country_squads",
        "tbl_flags",
        ["fk_flag"],
        ["flag_id"],
        source_schema="sch_shared",
        referent_schema="sch_shared",
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_tbl_competition_fk_flag",
        "tbl_competition",
        "tbl_flags",
        ["fk_flag"],
        ["flag_id"],
        source_schema="sch_shared",
        referent_schema="sch_shared",
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_country_squads_flag",
        "tbl_country_squads",
        schema="sch_shared",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_tbl_competition_fk_flag",
        "tbl_competition",
        schema="sch_shared",
        type_="foreignkey",
    )

    op.execute(
        "UPDATE sch_shared.tbl_country_squads"
        " SET fk_flag = LOWER(fk_flag) WHERE fk_flag IS NOT NULL"
    )
    op.execute(
        "UPDATE sch_shared.tbl_competition"
        " SET fk_flag = LOWER(fk_flag) WHERE fk_flag IS NOT NULL"
    )
    op.execute("UPDATE sch_shared.tbl_flags SET flag_id = LOWER(flag_id)")

    op.create_foreign_key(
        "fk_country_squads_flag",
        "tbl_country_squads",
        "tbl_flags",
        ["fk_flag"],
        ["flag_id"],
        source_schema="sch_shared",
        referent_schema="sch_shared",
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_tbl_competition_fk_flag",
        "tbl_competition",
        "tbl_flags",
        ["fk_flag"],
        ["flag_id"],
        source_schema="sch_shared",
        referent_schema="sch_shared",
        ondelete="SET NULL",
    )
