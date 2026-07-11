"""p8c_create_sch_football

Revision ID: p8c_create_sch_football
Revises: p8b_create_sch_shared
Create Date: 2026-07-11

Creates the sch_football schema for football-domain ORM models. All concrete
models inheriting from FootballBase must declare::

    __table_args__ = {"schema": "sch_football"}

The downgrade uses RESTRICT so the schema cannot be dropped while it still
contains tables added by later migrations.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "p8c_create_sch_football"
down_revision: str | Sequence[str] | None = "p8b_create_sch_shared"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS sch_football")


def downgrade() -> None:
    op.execute("DROP SCHEMA IF EXISTS sch_football RESTRICT")
