"""Reorder columns in sch_shared.tbl_flags: fk_country before flag_url.

- Target order: flag_id, fk_country, flag_url, created_at

Revision ID: p14j
Revises: p14i
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "p14j"
down_revision: str | None = "p14i"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Recreate tbl_flags with target order: flag_id, fk_country, flag_url, created_at
    op.execute(
        sa.text(
            """
            CREATE TABLE sch_shared.tbl_flags_new (
                flag_id     VARCHAR(2)   NOT NULL,
                fk_country  VARCHAR(10)  NOT NULL,
                flag_url    VARCHAR(500) NOT NULL,
                created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
                CONSTRAINT tbl_flags_new_pkey PRIMARY KEY (flag_id)
            )
            """
        )
    )
    op.execute(
        sa.text(
            "INSERT INTO sch_shared.tbl_flags_new"
            " (flag_id, fk_country, flag_url, created_at) "
            "SELECT flag_id, fk_country, flag_url, created_at"
            " FROM sch_shared.tbl_flags"
        )
    )
    op.execute(sa.text("DROP TABLE sch_shared.tbl_flags"))
    op.execute(
        sa.text("ALTER TABLE sch_shared.tbl_flags_new RENAME TO tbl_flags")
    )
    op.execute(
        sa.text(
            "ALTER INDEX sch_shared.tbl_flags_new_pkey RENAME TO tbl_flags_pkey"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX ix_flags_flag_id ON sch_shared.tbl_flags (flag_id)"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE sch_shared.tbl_flags "
            "ADD CONSTRAINT uq_flags_fk_country UNIQUE (fk_country)"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE sch_shared.tbl_flags "
            "ADD CONSTRAINT tbl_flags_fk_country_fkey "
            "FOREIGN KEY (fk_country) "
            "REFERENCES sch_shared.tbl_countries (country_id) ON DELETE CASCADE"
        )
    )


def downgrade() -> None:
    # Recreate tbl_flags with original order: flag_id, flag_url, fk_country, created_at
    op.execute(
        sa.text(
            """
            CREATE TABLE sch_shared.tbl_flags_new (
                flag_id     VARCHAR(2)   NOT NULL,
                flag_url    VARCHAR(500) NOT NULL,
                fk_country  VARCHAR(10)  NOT NULL,
                created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
                CONSTRAINT tbl_flags_new_pkey PRIMARY KEY (flag_id)
            )
            """
        )
    )
    op.execute(
        sa.text(
            "INSERT INTO sch_shared.tbl_flags_new"
            " (flag_id, flag_url, fk_country, created_at) "
            "SELECT flag_id, flag_url, fk_country, created_at"
            " FROM sch_shared.tbl_flags"
        )
    )
    op.execute(sa.text("DROP TABLE sch_shared.tbl_flags"))
    op.execute(
        sa.text("ALTER TABLE sch_shared.tbl_flags_new RENAME TO tbl_flags")
    )
    op.execute(
        sa.text(
            "ALTER INDEX sch_shared.tbl_flags_new_pkey RENAME TO tbl_flags_pkey"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX ix_flags_flag_id ON sch_shared.tbl_flags (flag_id)"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE sch_shared.tbl_flags "
            "ADD CONSTRAINT uq_flags_fk_country UNIQUE (fk_country)"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE sch_shared.tbl_flags "
            "ADD CONSTRAINT tbl_flags_fk_country_fkey "
            "FOREIGN KEY (fk_country) "
            "REFERENCES sch_shared.tbl_countries (country_id) ON DELETE CASCADE"
        )
    )
