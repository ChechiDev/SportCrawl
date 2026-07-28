"""Drop clubs_url from tbl_country_squads and add fk_country to scrape_queue.

clubs_url is now stored in sch_fbref_backend.tbl_country_squad_urls.
fk_country on scrape_queue lets workers resolve country without a join.

Revision ID: p49a
Revises: p48a
"""

import sqlalchemy as sa
from alembic import op

revision: str = "p49a"
down_revision: str | None = "p48a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(
        "ALTER TABLE sch_fbref_infra.scrape_queue ADD COLUMN fk_country VARCHAR(3) NULL"
    ))
    op.execute(sa.text(
        "ALTER TABLE sch_fbref_shared.tbl_country_squads DROP COLUMN clubs_url"
    ))


def downgrade() -> None:
    op.execute(sa.text(
        "ALTER TABLE sch_fbref_shared.tbl_country_squads"
        " ADD COLUMN clubs_url VARCHAR(500) NOT NULL DEFAULT ''"
    ))
    op.execute(sa.text(
        "ALTER TABLE sch_fbref_infra.scrape_queue DROP COLUMN fk_country"
    ))
