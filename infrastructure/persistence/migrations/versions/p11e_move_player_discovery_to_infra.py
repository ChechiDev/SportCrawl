"""p11e_move_player_discovery_to_infra

Revision ID: p11e
Revises: p11d
Create Date: 2026-07-15

Moves player_discovery_batch and player_queue_ref from sch_football to sch_infra,
and updates v_player_scrape_progress to reference the new schema.

Steps:
  1. Drop view sch_football.v_player_scrape_progress
  2. ALTER TABLE sch_football.player_queue_ref   SET SCHEMA sch_infra
  3. ALTER TABLE sch_football.player_discovery_batch SET SCHEMA sch_infra
  4. Recreate view in sch_football referencing sch_infra tables

Downgrade reverses all steps.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "p11e"
down_revision: str | Sequence[str] | None = "p11d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Drop view — references the tables being moved
    op.execute("DROP VIEW IF EXISTS sch_football.v_player_scrape_progress")

    # 2. Move player_queue_ref first (no dependents other than the view)
    op.execute("ALTER TABLE sch_football.player_queue_ref SET SCHEMA sch_infra")

    # 3. Move player_discovery_batch
    op.execute("ALTER TABLE sch_football.player_discovery_batch SET SCHEMA sch_infra")

    # 4. Recreate view in sch_football referencing sch_infra tables
    op.execute(
        """
        CREATE VIEW sch_football.v_player_scrape_progress AS
        SELECT
            pdb.country_id,
            pdb.total_urls,
            COUNT(sq.id) FILTER (WHERE sq.status = 'DONE') AS done,
            COUNT(sq.id) FILTER (WHERE sq.status = 'PENDING') AS pending,
            COUNT(sq.id) FILTER (WHERE sq.status = 'IN_PROGRESS') AS in_progress,
            COUNT(sq.id) FILTER (WHERE sq.status = 'FAILED') AS failed
        FROM sch_infra.player_discovery_batch pdb
        LEFT JOIN sch_infra.player_queue_ref pqr ON pqr.country_id = pdb.country_id
        LEFT JOIN sch_infra.scrape_queue sq ON sq.id = pqr.queue_id
        GROUP BY pdb.country_id, pdb.total_urls
        """
    )


def downgrade() -> None:
    # 1. Drop view
    op.execute("DROP VIEW IF EXISTS sch_football.v_player_scrape_progress")

    # 2. Move tables back to sch_football
    op.execute("ALTER TABLE sch_infra.player_queue_ref SET SCHEMA sch_football")
    op.execute("ALTER TABLE sch_infra.player_discovery_batch SET SCHEMA sch_football")

    # 3. Recreate view pointing to sch_football tables
    op.execute(
        """
        CREATE VIEW sch_football.v_player_scrape_progress AS
        SELECT
            pdb.country_id,
            pdb.total_urls,
            COUNT(sq.id) FILTER (WHERE sq.status = 'DONE') AS done,
            COUNT(sq.id) FILTER (WHERE sq.status = 'PENDING') AS pending,
            COUNT(sq.id) FILTER (WHERE sq.status = 'IN_PROGRESS') AS in_progress,
            COUNT(sq.id) FILTER (WHERE sq.status = 'FAILED') AS failed
        FROM sch_football.player_discovery_batch pdb
        LEFT JOIN sch_football.player_queue_ref pqr ON pqr.country_id = pdb.country_id
        LEFT JOIN sch_infra.scrape_queue sq ON sq.id = pqr.queue_id
        GROUP BY pdb.country_id, pdb.total_urls
        """
    )
