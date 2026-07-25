"""Create tbl_cities and normalize city_name in tbl_player_info.

Revision ID: p18a
Revises: p17a
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "p18a"
down_revision: str | None = "p17a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Create tbl_cities lookup table
    op.execute(
        sa.text(
            """
            CREATE TABLE sch_shared.tbl_cities (
                city_id SERIAL PRIMARY KEY,
                city_name VARCHAR(150) NOT NULL,
                CONSTRAINT uq_tbl_cities_city_name UNIQUE (city_name)
            )
            """
        )
    )

    # 2. Add fk_city column to tbl_player_info (nullable, no FK yet)
    op.execute(
        sa.text(
            "ALTER TABLE sch_shared.tbl_player_info ADD COLUMN fk_city INTEGER NULL"
        )
    )

    # 3. Backfill: insert distinct city_name values from tbl_player_info into tbl_cities
    op.execute(
        sa.text(
            """
            INSERT INTO sch_shared.tbl_cities (city_name)
            SELECT DISTINCT city_name
            FROM sch_shared.tbl_player_info
            WHERE city_name IS NOT NULL
            ON CONFLICT (city_name) DO NOTHING
            """
        )
    )

    # 4. Backfill: set fk_city on tbl_player_info from tbl_cities
    op.execute(
        sa.text(
            """
            UPDATE sch_shared.tbl_player_info pi
            SET fk_city = c.city_id
            FROM sch_shared.tbl_cities c
            WHERE pi.city_name = c.city_name
            """
        )
    )

    # 5. Add FK constraint
    op.execute(
        sa.text(
            """
            ALTER TABLE sch_shared.tbl_player_info
            ADD CONSTRAINT tbl_player_info_fk_city_fkey
            FOREIGN KEY (fk_city)
            REFERENCES sch_shared.tbl_cities (city_id)
            ON DELETE SET NULL
            """
        )
    )

    # 6. Create index on fk_city
    op.execute(
        sa.text(
            "CREATE INDEX ix_player_info_fk_city "
            "ON sch_shared.tbl_player_info (fk_city)"
        )
    )

    # 7. Drop city_name column
    op.execute(
        sa.text(
            "ALTER TABLE sch_shared.tbl_player_info DROP COLUMN city_name"
        )
    )


def downgrade() -> None:
    # 7 reversed — re-add city_name
    op.execute(
        sa.text(
            "ALTER TABLE sch_shared.tbl_player_info ADD COLUMN city_name VARCHAR(150) NULL"
        )
    )

    # 4 reversed — restore city_name strings from tbl_cities via JOIN
    op.execute(
        sa.text(
            """
            UPDATE sch_shared.tbl_player_info pi
            SET city_name = c.city_name
            FROM sch_shared.tbl_cities c
            WHERE pi.fk_city = c.city_id
            """
        )
    )

    # 6 reversed — drop index
    op.execute(
        sa.text("DROP INDEX sch_shared.ix_player_info_fk_city")
    )

    # 5 reversed — drop FK constraint
    op.execute(
        sa.text(
            "ALTER TABLE sch_shared.tbl_player_info "
            "DROP CONSTRAINT tbl_player_info_fk_city_fkey"
        )
    )

    # 2 reversed — drop fk_city column
    op.execute(
        sa.text(
            "ALTER TABLE sch_shared.tbl_player_info DROP COLUMN fk_city"
        )
    )

    # 1 reversed — drop tbl_cities
    op.execute(
        sa.text("DROP TABLE sch_shared.tbl_cities")
    )
