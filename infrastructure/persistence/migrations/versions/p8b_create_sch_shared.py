"""p8b_create_sch_shared

Revision ID: p8b_create_sch_shared
Revises: p8a_lockdown_public
Create Date: 2026-07-11

Creates the sch_shared schema for shared domain objects that are used across
multiple sports. The IF NOT EXISTS guard makes the upgrade idempotent.

The downgrade uses RESTRICT (the PostgreSQL default) so the schema cannot be
dropped if it still contains objects added by later migrations — a safe guard
that prevents accidentally destroying data when rolling back selectively.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "p8b_create_sch_shared"
down_revision: str | Sequence[str] | None = "p8a_lockdown_public"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS sch_shared")


def downgrade() -> None:
    op.execute("DROP SCHEMA IF EXISTS sch_shared RESTRICT")
