"""Add sch_shared.tbl_player_citizenship table.

Revision ID: p14l
Revises: p14k
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "p14l"
down_revision: str | None = "p14k"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            CREATE TABLE sch_shared.tbl_player_citizenship (
                player_id   VARCHAR(20)  NOT NULL,
                country_id  VARCHAR(10)  NOT NULL,
                CONSTRAINT tbl_player_citizenship_pkey
                    PRIMARY KEY (player_id, country_id),
                CONSTRAINT tbl_player_citizenship_player_id_fkey
                    FOREIGN KEY (player_id)
                    REFERENCES sch_shared.tbl_players (player_id) ON DELETE CASCADE,
                CONSTRAINT tbl_player_citizenship_country_id_fkey
                    FOREIGN KEY (country_id)
                    REFERENCES sch_shared.tbl_countries (country_id) ON DELETE RESTRICT
            )
            """
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX ix_player_citizenship_country_id "
            "ON sch_shared.tbl_player_citizenship (country_id)"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text("DROP TABLE sch_shared.tbl_player_citizenship")
    )
