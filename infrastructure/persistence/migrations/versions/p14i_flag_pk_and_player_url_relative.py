"""Make flag_id the PK for tbl_flags and store relative player URLs.

- tbl_flags: drop id column, promote flag_id to primary key
- tbl_players: strip https://fbref.com prefix from existing player_url values

Revision ID: p14i
Revises: p14h
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "p14i"
down_revision: str | None = "p14h"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- tbl_flags ---
    # Drop the index on flag_id (was just an index, not PK)
    op.drop_index("ix_flags_flag_id", table_name="tbl_flags", schema="sch_shared")

    # Drop existing PK constraint on id
    op.drop_constraint(
        "tbl_flags_pkey", "tbl_flags", schema="sch_shared", type_="primary"
    )

    # Add new PK on flag_id
    op.create_primary_key(
        "tbl_flags_pkey", "tbl_flags", ["flag_id"], schema="sch_shared"
    )

    # Drop the id column
    op.drop_column("tbl_flags", "id", schema="sch_shared")

    # --- tbl_players: strip absolute URL prefix ---
    op.execute(
        sa.text(
            "UPDATE sch_shared.tbl_players "
            "SET player_url = regexp_replace(player_url, '^https://fbref\\.com', '') "
            "WHERE player_url LIKE 'https://fbref.com%'"
        )
    )


def downgrade() -> None:
    # --- tbl_players: restore absolute URLs ---
    op.execute(
        sa.text(
            "UPDATE sch_shared.tbl_players "
            "SET player_url = 'https://fbref.com' || player_url "
            "WHERE player_url LIKE '/en/%'"
        )
    )

    # --- tbl_flags: restore id column and original PK ---
    op.add_column(
        "tbl_flags",
        sa.Column(
            "id",
            sa.String(),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        schema="sch_shared",
    )

    # Swap PK back to id
    op.drop_constraint(
        "tbl_flags_pkey", "tbl_flags", schema="sch_shared", type_="primary"
    )
    op.create_primary_key("tbl_flags_pkey", "tbl_flags", ["id"], schema="sch_shared")

    # IF NOT EXISTS: p14j downgrade may have already recreated this index
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_flags_flag_id"
        " ON sch_shared.tbl_flags (flag_id)"
    )
