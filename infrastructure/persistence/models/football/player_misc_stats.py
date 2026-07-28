"""ORM model for tbl_player_misc_stats in sch_fbref_football schema."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence.models.base import FootballBase


class PlayerMiscStats(FootballBase):
    """ORM model for sch_fbref_football.tbl_player_misc_stats.

    Stores per-season miscellaneous statistics for a player in a specific
    competition and team. Composite PK: (player_id, season, fk_team, fk_comp).
    """

    __tablename__ = "tbl_player_misc_stats"

    player_id: Mapped[str] = mapped_column(
        String(20),
        ForeignKey(
            "sch_fbref_shared.tbl_players.player_id",
            ondelete="CASCADE",
        ),
        primary_key=True,
        nullable=False,
    )
    season: Mapped[int] = mapped_column(SmallInteger, primary_key=True, nullable=False)
    fk_team: Mapped[str] = mapped_column(
        String(8),
        ForeignKey(
            "sch_fbref_shared.tbl_teams.team_id",
            ondelete="RESTRICT",
        ),
        primary_key=True,
        nullable=False,
    )
    fk_country: Mapped[str | None] = mapped_column(
        String(10),
        ForeignKey(
            "sch_fbref_shared.tbl_countries.country_id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    fk_comp: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(
            "sch_fbref_shared.tbl_competition.comp_id",
            ondelete="RESTRICT",
        ),
        primary_key=True,
        nullable=False,
    )

    min_per_90: Mapped[Decimal] = mapped_column(
        Numeric(6, 2), nullable=False, server_default="0.00"
    )
    yellow_cards: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="0"
    )
    red_cards: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="0"
    )
    yellow_red_cards: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="0"
    )
    fouls: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="0"
    )
    fouled: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="0"
    )
    offsides: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="0"
    )
    crosses: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="0"
    )
    interceptions: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="0"
    )
    tackles_won: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="0"
    )
    pk_won: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="0"
    )
    pk_conceded: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="0"
    )
    own_goals: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="0"
    )

    team_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    comp_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    match_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(nullable=True)

    __table_args__ = (
        Index("ix_tbl_player_misc_stats_season", "season"),
        Index("ix_tbl_player_misc_stats_fk_team", "fk_team"),
        Index("ix_tbl_player_misc_stats_fk_comp", "fk_comp"),
        {"schema": "sch_fbref_football"},
    )
