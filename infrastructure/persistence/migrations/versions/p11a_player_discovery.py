"""p11a_player_discovery

Revision ID: p11a
Revises: p10d_add_fk_ondelete
Create Date: 2026-07-12

Creates player-discovery tables and progress view:
  sch_shared.tbl_players          — player skeleton rows (natural PK: player_id)
  sch_shared.tbl_player_positions — per-player position codes with scrape order
  sch_football.player_discovery_batch — one row per country enqueue run
  sch_football.player_queue_ref       — links scrape_queue rows to a country
  sch_football.v_player_scrape_progress — aggregate view for monitoring

Creation order respects FK dependencies:
  tbl_players → tbl_player_positions  (positions FK → players)
  tbl_countries already exists (tbl_players FK → tbl_countries)
  player_discovery_batch → player_queue_ref  (both FK → tbl_countries)
  v_player_scrape_progress joins player_discovery_batch, player_queue_ref,
    and sch_infra.scrape_queue — view is created last.

Downgrade drops in reverse order: view first, then children before parents.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "p11a"
down_revision: str | Sequence[str] | None = "p10d_add_fk_ondelete"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. sch_shared.tbl_players — natural PK, no surrogate
    op.create_table(
        "tbl_players",
        sa.Column("player_id", sa.String(20), primary_key=True),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("full_name", sa.String(200), nullable=True),
        sa.Column("career_start", sa.SmallInteger, nullable=False),
        sa.Column("career_end", sa.SmallInteger, nullable=True),
        sa.Column(
            "fk_country_team",
            sa.String(10),
            sa.ForeignKey(
                "sch_shared.tbl_countries.country_id",
                ondelete="SET NULL",
                name="tbl_players_fk_country_team_fkey",
            ),
            nullable=True,
        ),
        sa.Column("player_url", sa.String(500), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        schema="sch_shared",
    )
    op.create_index(
        "ix_players_fk_country_team",
        "tbl_players",
        ["fk_country_team"],
        schema="sch_shared",
    )

    # 2. sch_shared.tbl_player_positions — composite PK, CASCADE from tbl_players
    op.create_table(
        "tbl_player_positions",
        sa.Column(
            "fk_player",
            sa.String(20),
            sa.ForeignKey(
                "sch_shared.tbl_players.player_id",
                ondelete="CASCADE",
                name="tbl_player_positions_fk_player_fkey",
            ),
            primary_key=True,
        ),
        sa.Column("position_code", sa.String(10), primary_key=True),
        sa.Column("sort_order", sa.SmallInteger, nullable=False),
        schema="sch_shared",
    )

    # 3. sch_football.player_discovery_batch — country_id is the natural PK
    op.create_table(
        "player_discovery_batch",
        sa.Column(
            "country_id",
            sa.String(10),
            sa.ForeignKey(
                "sch_shared.tbl_countries.country_id",
                ondelete="CASCADE",
                name="player_discovery_batch_country_id_fkey",
            ),
            primary_key=True,
        ),
        sa.Column("total_urls", sa.Integer, nullable=False),
        sa.Column(
            "enqueued_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        schema="sch_football",
    )

    # 4. sch_football.player_queue_ref
    op.create_table(
        "player_queue_ref",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "queue_id",
            sa.Integer,
            sa.ForeignKey(
                "sch_infra.scrape_queue.id",
                ondelete="CASCADE",
                name="player_queue_ref_queue_id_fkey",
            ),
            nullable=False,
        ),
        sa.Column(
            "country_id",
            sa.String(10),
            sa.ForeignKey(
                "sch_shared.tbl_countries.country_id",
                ondelete="CASCADE",
                name="player_queue_ref_country_id_fkey",
            ),
            nullable=False,
        ),
        schema="sch_football",
    )
    op.create_unique_constraint(
        "uq_player_queue_ref_queue_id",
        "player_queue_ref",
        ["queue_id"],
        schema="sch_football",
    )
    op.create_index(
        "ix_player_queue_ref_queue_id",
        "player_queue_ref",
        ["queue_id"],
        schema="sch_football",
    )
    op.create_index(
        "ix_player_queue_ref_country_id",
        "player_queue_ref",
        ["country_id"],
        schema="sch_football",
    )

    # 5. sch_football.v_player_scrape_progress — aggregate view
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


def downgrade() -> None:
    # Drop view first — it references the tables below
    op.execute("DROP VIEW IF EXISTS sch_football.v_player_scrape_progress")

    # Drop indexes and constraints on player_queue_ref before dropping the table
    op.drop_index(
        "ix_player_queue_ref_country_id",
        table_name="player_queue_ref",
        schema="sch_football",
    )
    op.drop_index(
        "ix_player_queue_ref_queue_id",
        table_name="player_queue_ref",
        schema="sch_football",
    )
    op.drop_constraint(
        "uq_player_queue_ref_queue_id",
        "player_queue_ref",
        schema="sch_football",
        type_="unique",
    )

    # Drop children before parents
    op.drop_table("player_queue_ref", schema="sch_football")
    op.drop_table("player_discovery_batch", schema="sch_football")
    op.drop_table("tbl_player_positions", schema="sch_shared")
    op.drop_index(
        "ix_players_fk_country_team",
        table_name="tbl_players",
        schema="sch_shared",
    )
    op.drop_table("tbl_players", schema="sch_shared")
