"""Add fk_url_registry_id column to scrape_queue.

Adds a nullable BIGINT column ``fk_url_registry_id`` to
``sch_fbref_infra.scrape_queue``.

No FK constraint is defined because the column is a soft (polymorphic)
reference that may point to any of the five URL-registry tables
(tbl_player_urls, tbl_team_urls, tbl_competition_urls, tbl_match_urls,
tbl_squad_urls) in sch_fbref_backend.  A real FK would require a single
target table or a supertype table, neither of which exists.  The column
is therefore a logical reference only: callers must enforce referential
integrity at the application layer.

Revision ID: p42a
Revises: p41a
"""

import sqlalchemy as sa
from alembic import op

revision: str = "p42a"
down_revision: str | None = "p41a"
branch_labels = None
depends_on = None

_SCHEMA = "sch_fbref_infra"
_TABLE = "scrape_queue"
_COLUMN = "fk_url_registry_id"
_INDEX = "ix_scrape_queue_url_registry"


def upgrade() -> None:
    op.add_column(
        _TABLE,
        sa.Column(_COLUMN, sa.BigInteger(), nullable=True),
        schema=_SCHEMA,
    )
    op.execute(
        f"""
        CREATE INDEX {_INDEX}
            ON {_SCHEMA}.{_TABLE} ({_COLUMN})
            WHERE {_COLUMN} IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {_SCHEMA}.{_INDEX}")
    op.drop_column(_TABLE, _COLUMN, schema=_SCHEMA)
