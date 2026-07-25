"""Restructure tbl_player_info: reorder columns, rename fk_national_team → fk_nat_team,
add player_age and fk_team, remove club_name and club_url.

Revision ID: p19a
Revises: p18a
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "p19a"
down_revision: str | None = "p18a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Create replacement table with correct column order
    op.execute(
        sa.text(
            """
            CREATE TABLE sch_shared.tbl_player_info_new (
                player_id      VARCHAR(20) NOT NULL,
                fk_country_birth VARCHAR(10) NULL,
                fk_city        INTEGER NULL,
                fk_nat_team    VARCHAR(10) NULL,
                fk_youth_nat_team VARCHAR(10) NULL,
                fk_team        VARCHAR(8) NULL,
                player_born    DATE NULL,
                player_age     INTEGER NULL,
                player_height  SMALLINT NULL,
                player_weight  SMALLINT NULL,
                player_foot    VARCHAR(20) NULL,
                fk_ply_pos_1   INTEGER NULL,
                fk_ply_pos_2   INTEGER NULL,
                fk_ply_pos_3   INTEGER NULL,
                player_wages   INTEGER NULL,
                player_expires DATE NULL,
                player_info_url VARCHAR(500) NOT NULL,
                created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at     TIMESTAMPTZ NULL,
                CONSTRAINT tbl_player_info_player_id_fkey
                    FOREIGN KEY (player_id)
                    REFERENCES sch_shared.tbl_players(player_id)
                    ON DELETE CASCADE,
                CONSTRAINT tbl_player_info_fk_country_birth_fkey
                    FOREIGN KEY (fk_country_birth)
                    REFERENCES sch_shared.tbl_countries(country_id)
                    ON DELETE SET NULL,
                CONSTRAINT tbl_player_info_fk_city_fkey
                    FOREIGN KEY (fk_city)
                    REFERENCES sch_shared.tbl_cities(city_id)
                    ON DELETE SET NULL,
                CONSTRAINT tbl_player_info_fk_nat_team_fkey
                    FOREIGN KEY (fk_nat_team)
                    REFERENCES sch_shared.tbl_countries(country_id)
                    ON DELETE SET NULL,
                CONSTRAINT tbl_player_info_fk_youth_nat_team_fkey
                    FOREIGN KEY (fk_youth_nat_team)
                    REFERENCES sch_shared.tbl_countries(country_id)
                    ON DELETE SET NULL,
                CONSTRAINT tbl_player_info_fk_team_fkey
                    FOREIGN KEY (fk_team)
                    REFERENCES sch_shared.tbl_teams(team_id)
                    ON DELETE SET NULL,
                CONSTRAINT tbl_player_info_fk_ply_pos_1_fkey
                    FOREIGN KEY (fk_ply_pos_1)
                    REFERENCES sch_shared.tbl_player_positions(position_id)
                    ON DELETE SET NULL,
                CONSTRAINT tbl_player_info_fk_ply_pos_2_fkey
                    FOREIGN KEY (fk_ply_pos_2)
                    REFERENCES sch_shared.tbl_player_positions(position_id)
                    ON DELETE SET NULL,
                CONSTRAINT tbl_player_info_fk_ply_pos_3_fkey
                    FOREIGN KEY (fk_ply_pos_3)
                    REFERENCES sch_shared.tbl_player_positions(position_id)
                    ON DELETE SET NULL,
                PRIMARY KEY (player_id)
            )
            """
        )
    )

    # 2. Copy data with transformations:
    #    - fk_nat_team  ← old fk_national_team
    #    - fk_team      ← extract from club_url; only if team exists in tbl_teams
    #    - player_age   ← EXTRACT(YEAR FROM AGE(player_born))
    #    - club_name / club_url are intentionally dropped
    op.execute(
        sa.text(
            """
            INSERT INTO sch_shared.tbl_player_info_new (
                player_id,
                fk_country_birth,
                fk_city,
                fk_nat_team,
                fk_youth_nat_team,
                fk_team,
                player_born,
                player_age,
                player_height,
                player_weight,
                player_foot,
                fk_ply_pos_1,
                fk_ply_pos_2,
                fk_ply_pos_3,
                player_wages,
                player_expires,
                player_info_url,
                created_at,
                updated_at
            )
            SELECT
                player_id,
                fk_country_birth,
                fk_city,
                fk_national_team,
                fk_youth_nat_team,
                CASE
                    WHEN SUBSTRING(club_url FROM '/en/squads/([a-f0-9]{8})/') IN (
                        SELECT team_id FROM sch_shared.tbl_teams
                    )
                    THEN SUBSTRING(club_url FROM '/en/squads/([a-f0-9]{8})/')
                    ELSE NULL
                END,
                player_born,
                CASE
                    WHEN player_born IS NOT NULL
                    THEN EXTRACT(YEAR FROM AGE(player_born))::INTEGER
                    ELSE NULL
                END,
                player_height,
                player_weight,
                player_foot,
                fk_ply_pos_1,
                fk_ply_pos_2,
                fk_ply_pos_3,
                player_wages,
                player_expires,
                player_info_url,
                created_at,
                updated_at
            FROM sch_shared.tbl_player_info
            """
        )
    )

    # 3. Drop old table (CASCADE drops dependent views/FKs)
    op.execute(
        sa.text("DROP TABLE sch_shared.tbl_player_info CASCADE")
    )

    # 4. Rename new table to canonical name
    op.execute(
        sa.text(
            "ALTER TABLE sch_shared.tbl_player_info_new RENAME TO tbl_player_info"
        )
    )

    # 5. Create indexes
    op.execute(
        sa.text(
            "CREATE INDEX ix_player_info_fk_country_birth "
            "ON sch_shared.tbl_player_info (fk_country_birth)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX ix_player_info_fk_city "
            "ON sch_shared.tbl_player_info (fk_city)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX ix_player_info_fk_nat_team "
            "ON sch_shared.tbl_player_info (fk_nat_team)"
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
            "CREATE INDEX ix_player_info_fk_team "
            "ON sch_shared.tbl_player_info (fk_team)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX ix_player_info_fk_ply_pos_1 "
            "ON sch_shared.tbl_player_info (fk_ply_pos_1)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX ix_player_info_fk_ply_pos_2 "
            "ON sch_shared.tbl_player_info (fk_ply_pos_2)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX ix_player_info_fk_ply_pos_3 "
            "ON sch_shared.tbl_player_info (fk_ply_pos_3)"
        )
    )


def downgrade() -> None:
    # NOTE: club_name data is NOT restored (was dropped in upgrade).
    # club_url is backfilled from fk_team via tbl_teams.team_url where possible.

    # 1. Recreate old table with original column order and column names
    op.execute(
        sa.text(
            """
            CREATE TABLE sch_shared.tbl_player_info_old (
                player_id        VARCHAR(20) NOT NULL,
                fk_country_birth VARCHAR(10) NULL,
                fk_national_team VARCHAR(10) NULL,
                fk_city          INTEGER NULL,
                player_born      DATE NULL,
                player_height    SMALLINT NULL,
                player_weight    SMALLINT NULL,
                fk_ply_pos_1     INTEGER NULL,
                fk_ply_pos_2     INTEGER NULL,
                fk_ply_pos_3     INTEGER NULL,
                player_foot      VARCHAR(20) NULL,
                player_wages     INTEGER NULL,
                player_expires   DATE NULL,
                fk_youth_nat_team VARCHAR(10) NULL,
                club_name        VARCHAR(200) NULL,
                club_url         VARCHAR(500) NULL,
                player_info_url  VARCHAR(500) NOT NULL,
                created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at       TIMESTAMPTZ NULL,
                CONSTRAINT tbl_player_info_player_id_fkey
                    FOREIGN KEY (player_id)
                    REFERENCES sch_shared.tbl_players(player_id)
                    ON DELETE CASCADE,
                CONSTRAINT tbl_player_info_fk_country_birth_fkey
                    FOREIGN KEY (fk_country_birth)
                    REFERENCES sch_shared.tbl_countries(country_id)
                    ON DELETE SET NULL,
                CONSTRAINT tbl_player_info_fk_national_team_fkey
                    FOREIGN KEY (fk_national_team)
                    REFERENCES sch_shared.tbl_countries(country_id)
                    ON DELETE SET NULL,
                CONSTRAINT tbl_player_info_fk_city_fkey
                    FOREIGN KEY (fk_city)
                    REFERENCES sch_shared.tbl_cities(city_id)
                    ON DELETE SET NULL,
                CONSTRAINT tbl_player_info_fk_youth_nat_team_fkey
                    FOREIGN KEY (fk_youth_nat_team)
                    REFERENCES sch_shared.tbl_countries(country_id)
                    ON DELETE SET NULL,
                CONSTRAINT tbl_player_info_fk_ply_pos_1_fkey
                    FOREIGN KEY (fk_ply_pos_1)
                    REFERENCES sch_shared.tbl_player_positions(position_id)
                    ON DELETE SET NULL,
                CONSTRAINT tbl_player_info_fk_ply_pos_2_fkey
                    FOREIGN KEY (fk_ply_pos_2)
                    REFERENCES sch_shared.tbl_player_positions(position_id)
                    ON DELETE SET NULL,
                CONSTRAINT tbl_player_info_fk_ply_pos_3_fkey
                    FOREIGN KEY (fk_ply_pos_3)
                    REFERENCES sch_shared.tbl_player_positions(position_id)
                    ON DELETE SET NULL,
                PRIMARY KEY (player_id)
            )
            """
        )
    )

    # 2. Copy data back; backfill club_url from tbl_teams.team_url where fk_team exists
    op.execute(
        sa.text(
            """
            INSERT INTO sch_shared.tbl_player_info_old (
                player_id,
                fk_country_birth,
                fk_national_team,
                fk_city,
                player_born,
                player_height,
                player_weight,
                fk_ply_pos_1,
                fk_ply_pos_2,
                fk_ply_pos_3,
                player_foot,
                player_wages,
                player_expires,
                fk_youth_nat_team,
                club_name,
                club_url,
                player_info_url,
                created_at,
                updated_at
            )
            SELECT
                pi.player_id,
                pi.fk_country_birth,
                pi.fk_nat_team,
                pi.fk_city,
                pi.player_born,
                pi.player_height,
                pi.player_weight,
                pi.fk_ply_pos_1,
                pi.fk_ply_pos_2,
                pi.fk_ply_pos_3,
                pi.player_foot,
                pi.player_wages,
                pi.player_expires,
                pi.fk_youth_nat_team,
                NULL,
                t.team_url,
                pi.player_info_url,
                pi.created_at,
                pi.updated_at
            FROM sch_shared.tbl_player_info pi
            LEFT JOIN sch_shared.tbl_teams t ON pi.fk_team = t.team_id
            """
        )
    )

    # 3. Drop new table
    op.execute(
        sa.text("DROP TABLE sch_shared.tbl_player_info CASCADE")
    )

    # 4. Rename old table back
    op.execute(
        sa.text(
            "ALTER TABLE sch_shared.tbl_player_info_old RENAME TO tbl_player_info"
        )
    )

    # 5. Recreate original indexes
    op.execute(
        sa.text(
            "CREATE INDEX ix_player_info_fk_country_birth "
            "ON sch_shared.tbl_player_info (fk_country_birth)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX ix_player_info_fk_national_team "
            "ON sch_shared.tbl_player_info (fk_national_team)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX ix_player_info_fk_city "
            "ON sch_shared.tbl_player_info (fk_city)"
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
            "CREATE INDEX ix_player_info_fk_ply_pos_1 "
            "ON sch_shared.tbl_player_info (fk_ply_pos_1)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX ix_player_info_fk_ply_pos_2 "
            "ON sch_shared.tbl_player_info (fk_ply_pos_2)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX ix_player_info_fk_ply_pos_3 "
            "ON sch_shared.tbl_player_info (fk_ply_pos_3)"
        )
    )
