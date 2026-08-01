"""Create backend URL tables in sch_fbref_backend.

Revision ID: p40a
Revises: p39a
"""

import sqlalchemy as sa
from alembic import op

revision: str = "p40a"
down_revision: str | None = "p39a"
branch_labels = None
depends_on = None

_SCHEMA = "sch_fbref_backend"
_SHARED = "sch_fbref_shared"

_COMMON_COLUMNS = [
    sa.Column("url_type", sa.String(50), nullable=False),
    sa.Column("url", sa.String(500), nullable=False),
    sa.Column(
        "status",
        sa.String(20),
        nullable=False,
        server_default="PENDING",
    ),
    sa.Column(
        "cadence_hours",
        sa.SmallInteger,
        nullable=False,
        server_default="168",
    ),
    sa.Column("last_scraped_at", sa.TIMESTAMP(timezone=True), nullable=True),
    sa.Column(
        "next_scrape_at",
        sa.TIMESTAMP(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    ),
    sa.Column("last_scrape_status", sa.String(20), nullable=True),
    sa.Column("priority", sa.SmallInteger, nullable=False, server_default="5"),
    sa.Column("retry_count", sa.SmallInteger, nullable=False, server_default="0"),
    sa.Column("last_error", sa.Text, nullable=True),
    sa.Column(
        "created_at",
        sa.TIMESTAMP(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    ),
    sa.Column(
        "updated_at",
        sa.TIMESTAMP(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    ),
]


def _common_constraints(table: str) -> list[sa.CheckConstraint]:
    return [
        sa.CheckConstraint(
            "priority BETWEEN 1 AND 10", name=f"ck_{table}_priority"
        ),
        sa.CheckConstraint(
            "cadence_hours > 0", name=f"ck_{table}_cadence_hours"
        ),
        sa.CheckConstraint(
            "retry_count >= 0", name=f"ck_{table}_retry_count"
        ),
    ]


def upgrade() -> None:
    # --- tbl_player_urls ---
    op.create_table(
        "tbl_player_urls",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "fk_player",
            sa.String(20),
            sa.ForeignKey(
                f"{_SHARED}.tbl_players.player_id",
                ondelete="CASCADE",
                name="tbl_player_urls_fk_player_fkey",
            ),
            nullable=False,
        ),
        *_COMMON_COLUMNS,  # type: ignore[arg-type]
        sa.UniqueConstraint(
            "fk_player", "url_type", name="uq_player_urls_player_url_type"
        ),
        *_common_constraints("player_urls"),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_player_urls_due",
        "tbl_player_urls",
        ["next_scrape_at", "priority"],
        schema=_SCHEMA,
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )
    op.create_index(
        "ix_player_urls_fk_player",
        "tbl_player_urls",
        ["fk_player"],
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_player_urls_status",
        "tbl_player_urls",
        ["status"],
        schema=_SCHEMA,
    )

    # --- tbl_team_urls ---
    op.create_table(
        "tbl_team_urls",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "fk_team",
            sa.String(8),
            sa.ForeignKey(
                f"{_SHARED}.tbl_teams.team_id",
                ondelete="CASCADE",
                name="tbl_team_urls_fk_team_fkey",
            ),
            nullable=False,
        ),
        *_COMMON_COLUMNS,  # type: ignore[arg-type]
        sa.UniqueConstraint("fk_team", "url_type", name="uq_team_urls_team_url_type"),
        *_common_constraints("team_urls"),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_team_urls_due",
        "tbl_team_urls",
        ["next_scrape_at", "priority"],
        schema=_SCHEMA,
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )
    op.create_index(
        "ix_team_urls_fk_team",
        "tbl_team_urls",
        ["fk_team"],
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_team_urls_status",
        "tbl_team_urls",
        ["status"],
        schema=_SCHEMA,
    )

    # --- tbl_competition_urls ---
    op.create_table(
        "tbl_competition_urls",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "fk_comp",
            sa.Integer,
            sa.ForeignKey(
                f"{_SHARED}.tbl_competition.comp_id",
                ondelete="CASCADE",
                name="tbl_competition_urls_fk_comp_fkey",
            ),
            nullable=False,
        ),
        *_COMMON_COLUMNS,  # type: ignore[arg-type]
        sa.UniqueConstraint(
            "fk_comp", "url_type", name="uq_competition_urls_comp_url_type"
        ),
        *_common_constraints("competition_urls"),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_competition_urls_due",
        "tbl_competition_urls",
        ["next_scrape_at", "priority"],
        schema=_SCHEMA,
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )
    op.create_index(
        "ix_competition_urls_fk_comp",
        "tbl_competition_urls",
        ["fk_comp"],
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_competition_urls_status",
        "tbl_competition_urls",
        ["status"],
        schema=_SCHEMA,
    )

    # --- tbl_country_urls ---
    op.create_table(
        "tbl_country_urls",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "fk_country",
            sa.String(10),
            sa.ForeignKey(
                f"{_SHARED}.tbl_countries.country_id",
                ondelete="CASCADE",
                name="tbl_country_urls_fk_country_fkey",
            ),
            nullable=False,
        ),
        *_COMMON_COLUMNS,  # type: ignore[arg-type]
        sa.UniqueConstraint(
            "fk_country", "url_type", name="uq_country_urls_country_url_type"
        ),
        sa.CheckConstraint(
            "url_type IN ('country', 'players_list')",
            name="ck_country_urls_url_type",
        ),
        *_common_constraints("country_urls"),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_country_urls_due",
        "tbl_country_urls",
        ["next_scrape_at", "priority"],
        schema=_SCHEMA,
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )
    op.create_index(
        "ix_country_urls_fk_country",
        "tbl_country_urls",
        ["fk_country"],
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_country_urls_status",
        "tbl_country_urls",
        ["status"],
        schema=_SCHEMA,
    )

    # --- tbl_country_squad_urls ---
    op.create_table(
        "tbl_country_squad_urls",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "fk_country",
            sa.String(10),
            sa.ForeignKey(
                f"{_SHARED}.tbl_countries.country_id",
                ondelete="CASCADE",
                name="tbl_country_squad_urls_fk_country_fkey",
            ),
            nullable=False,
        ),
        *_COMMON_COLUMNS,  # type: ignore[arg-type]
        sa.UniqueConstraint(
            "fk_country", "url_type", name="uq_country_squad_urls_country_url_type"
        ),
        sa.CheckConstraint(
            "url_type IN ('clubs', 'nat_team_men', 'nat_team_women')",
            name="ck_country_squad_urls_url_type",
        ),
        *_common_constraints("country_squad_urls"),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_country_squad_urls_due",
        "tbl_country_squad_urls",
        ["next_scrape_at", "priority"],
        schema=_SCHEMA,
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )
    op.create_index(
        "ix_country_squad_urls_fk_country",
        "tbl_country_squad_urls",
        ["fk_country"],
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_country_squad_urls_status",
        "tbl_country_squad_urls",
        ["status"],
        schema=_SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("tbl_country_squad_urls", schema=_SCHEMA)
    op.drop_table("tbl_country_urls", schema=_SCHEMA)
    op.drop_table("tbl_competition_urls", schema=_SCHEMA)
    op.drop_table("tbl_team_urls", schema=_SCHEMA)
    op.drop_table("tbl_player_urls", schema=_SCHEMA)
