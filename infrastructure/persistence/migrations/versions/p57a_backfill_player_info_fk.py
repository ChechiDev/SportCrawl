"""p57a: backfill fk_url_registry_id for player_info queue rows with NULL FK.

Existing scrape_queue rows for job_type='player_info' may have fk_url_registry_id=NULL
because they were inserted before the FK column was added. This migration populates
the FK by matching on URL, skipping IN_PROGRESS and FAILED rows.
"""

from alembic import op

revision = "p57a"
down_revision = "p56a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE sch_fbref_infra.scrape_queue sq
        SET fk_url_registry_id = bpu.id
        FROM sch_fbref_backend.tbl_player_urls bpu
        WHERE sq.job_type = 'player_info'
          AND sq.fk_url_registry_id IS NULL
          AND sq.url = bpu.url
          AND sq.status NOT IN ('IN_PROGRESS', 'FAILED')
        """
    )


def downgrade() -> None:
    # Intentional no-op: cannot determine which NULLs were backfilled.
    pass
