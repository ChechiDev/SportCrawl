"""Fix tbl_player_citizenship schema; drop fk_citizenship from tbl_player_info.

Revision ID: p17a
Revises: p16b
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "p17a"
down_revision: str | None = "p16b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Rename country_id → fk_country in tbl_player_citizenship
    op.execute(
        sa.text(
            "ALTER TABLE sch_shared.tbl_player_citizenship "
            "RENAME COLUMN country_id TO fk_country"
        )
    )

    # 2. Rename index on tbl_player_citizenship
    op.execute(
        sa.text(
            "ALTER INDEX sch_shared.ix_player_citizenship_country_id "
            "RENAME TO ix_tbl_player_citizenship_fk_country"
        )
    )

    # 3. Backfill from tbl_player_info.fk_citizenship
    op.execute(
        sa.text(
            """
            INSERT INTO sch_shared.tbl_player_citizenship (player_id, fk_country)
            SELECT player_id, fk_citizenship
            FROM sch_shared.tbl_player_info
            WHERE fk_citizenship IS NOT NULL
            ON CONFLICT DO NOTHING
            """
        )
    )

    # 4. Drop index on fk_citizenship
    op.execute(sa.text("DROP INDEX sch_shared.ix_player_info_fk_citizenship"))

    # 5. Drop FK constraint on fk_citizenship
    op.execute(
        sa.text(
            "ALTER TABLE sch_shared.tbl_player_info "
            "DROP CONSTRAINT tbl_player_info_fk_citizenship_fkey"
        )
    )

    # 6. Drop fk_citizenship column
    op.execute(
        sa.text("ALTER TABLE sch_shared.tbl_player_info DROP COLUMN fk_citizenship")
    )


def downgrade() -> None:
    # 6 reversed — re-add fk_citizenship column (backfill data is NOT restored)
    op.execute(
        sa.text(
            "ALTER TABLE sch_shared.tbl_player_info "
            "ADD COLUMN fk_citizenship VARCHAR(10) NULL"
        )
    )

    # 5 reversed — re-add FK constraint
    op.execute(
        sa.text(
            "ALTER TABLE sch_shared.tbl_player_info "
            "ADD CONSTRAINT tbl_player_info_fk_citizenship_fkey "
            "FOREIGN KEY (fk_citizenship) "
            "REFERENCES sch_shared.tbl_countries (country_id) ON DELETE SET NULL"
        )
    )

    # 4 reversed — re-add index
    op.execute(
        sa.text(
            "CREATE INDEX ix_player_info_fk_citizenship "
            "ON sch_shared.tbl_player_info (fk_citizenship)"
        )
    )

    # 3 reversed — backfill not restored (rows remain in tbl_player_citizenship)

    # 2 reversed — rename index back
    op.execute(
        sa.text(
            "ALTER INDEX sch_shared.ix_tbl_player_citizenship_fk_country "
            "RENAME TO ix_player_citizenship_country_id"
        )
    )

    # 1 reversed — rename fk_country → country_id
    op.execute(
        sa.text(
            "ALTER TABLE sch_shared.tbl_player_citizenship "
            "RENAME COLUMN fk_country TO country_id"
        )
    )
