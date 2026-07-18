"""Add citizenship, youth team, club to tbl_player_info.

Revision ID: p14m
Revises: p14l
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "p14m"
down_revision: str | None = "p14l"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "ALTER TABLE sch_shared.tbl_player_info "
            "ADD COLUMN fk_citizenship VARCHAR(10) NULL"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE sch_shared.tbl_player_info "
            "ADD CONSTRAINT tbl_player_info_fk_citizenship_fkey "
            "FOREIGN KEY (fk_citizenship) "
            "REFERENCES sch_shared.tbl_countries (country_id) ON DELETE SET NULL"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX ix_player_info_fk_citizenship "
            "ON sch_shared.tbl_player_info (fk_citizenship)"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE sch_shared.tbl_player_info "
            "ADD COLUMN fk_youth_nat_team VARCHAR(10) NULL"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE sch_shared.tbl_player_info "
            "ADD CONSTRAINT tbl_player_info_fk_youth_nat_team_fkey "
            "FOREIGN KEY (fk_youth_nat_team) "
            "REFERENCES sch_shared.tbl_countries (country_id) ON DELETE SET NULL"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX ix_player_info_fk_youth_nat_team "
            "ON sch_shared.tbl_player_info (fk_youth_nat_team)"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE sch_shared.tbl_player_info "
            "ADD COLUMN club_name VARCHAR(200) NULL"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE sch_shared.tbl_player_info "
            "ADD COLUMN club_url VARCHAR(500) NULL"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "ALTER TABLE sch_shared.tbl_player_info DROP COLUMN club_url"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE sch_shared.tbl_player_info DROP COLUMN club_name"
        )
    )
    op.execute(
        sa.text(
            "DROP INDEX sch_shared.ix_player_info_fk_youth_nat_team"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE sch_shared.tbl_player_info "
            "DROP CONSTRAINT tbl_player_info_fk_youth_nat_team_fkey"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE sch_shared.tbl_player_info DROP COLUMN fk_youth_nat_team"
        )
    )
    op.execute(
        sa.text(
            "DROP INDEX sch_shared.ix_player_info_fk_citizenship"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE sch_shared.tbl_player_info "
            "DROP CONSTRAINT tbl_player_info_fk_citizenship_fkey"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE sch_shared.tbl_player_info DROP COLUMN fk_citizenship"
        )
    )
