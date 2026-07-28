"""Fix scrape_queue column types and job_type nullability.

Changes to sch_fbref_infra.scrape_queue:
  - job_type: String(50) nullable → NOT NULL DEFAULT 'default'
    Fixes silent duplicate inserts: UNIQUE(url, job_type) with nullable
    job_type means NULL != NULL in PostgreSQL, bypassing the constraint.
  - url: Text → VARCHAR(2048)
  - domain: Text → VARCHAR(255)

Revision ID: p38a
Revises: p37a
"""

import sqlalchemy as sa
from alembic import op

revision: str = "p38a"
down_revision: str | None = "p37a"
branch_labels = None
depends_on = None

_SCHEMA = "sch_fbref_infra"
_TABLE = "scrape_queue"


def upgrade() -> None:
    # Backfill any existing NULL job_type rows before adding the NOT NULL constraint.
    op.execute(
        sa.text(
            f"UPDATE {_SCHEMA}.{_TABLE} SET job_type = 'default' WHERE job_type IS NULL"
        )
    )

    # Set server-side DEFAULT so future inserts without job_type get 'default'.
    op.execute(
        sa.text(
            f"ALTER TABLE {_SCHEMA}.{_TABLE}"
            " ALTER COLUMN job_type SET DEFAULT 'default'"
        )
    )

    # Now it is safe to enforce NOT NULL.
    op.alter_column(
        _TABLE,
        "job_type",
        existing_type=sa.String(50),
        nullable=False,
        schema=_SCHEMA,
    )

    # Narrow url from unbounded Text to VARCHAR(2048).
    op.alter_column(
        _TABLE,
        "url",
        existing_type=sa.Text(),
        type_=sa.String(2048),
        nullable=False,
        schema=_SCHEMA,
    )

    # Narrow domain from unbounded Text to VARCHAR(255).
    op.alter_column(
        _TABLE,
        "domain",
        existing_type=sa.Text(),
        type_=sa.String(255),
        nullable=False,
        schema=_SCHEMA,
    )


def downgrade() -> None:
    # Widen domain back to unbounded Text.
    op.alter_column(
        _TABLE,
        "domain",
        existing_type=sa.String(255),
        type_=sa.Text(),
        nullable=False,
        schema=_SCHEMA,
    )

    # Widen url back to unbounded Text.
    op.alter_column(
        _TABLE,
        "url",
        existing_type=sa.String(2048),
        type_=sa.Text(),
        nullable=False,
        schema=_SCHEMA,
    )

    # Drop the server default first, then allow NULLs again.
    op.execute(
        sa.text(
            f"ALTER TABLE {_SCHEMA}.{_TABLE}"
            " ALTER COLUMN job_type DROP DEFAULT"
        )
    )

    op.alter_column(
        _TABLE,
        "job_type",
        existing_type=sa.String(50),
        nullable=True,
        schema=_SCHEMA,
    )
