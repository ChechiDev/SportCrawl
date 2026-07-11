"""p8a_lockdown_public

Revision ID: p8a_lockdown_public
Revises: 5ab3b4f7d8a7
Create Date: 2026-07-11

Locks down the public schema by revoking default privileges that PostgreSQL
grants to all roles. After this migration, no role can create objects or
access tables in the public schema without an explicit GRANT.

This is a security hardening step that enforces the principle of least
privilege: only explicitly managed schemas (sch_infra, sch_shared,
sch_football) are accessible to application roles.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "p8a_lockdown_public"
down_revision: str | Sequence[str] | None = "5ab3b4f7d8a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
    op.execute("REVOKE USAGE ON SCHEMA public FROM PUBLIC")
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC")


def downgrade() -> None:
    op.execute("GRANT ALL ON ALL TABLES IN SCHEMA public TO PUBLIC")
    op.execute("GRANT USAGE ON SCHEMA public TO PUBLIC")
    op.execute("GRANT CREATE ON SCHEMA public TO PUBLIC")
