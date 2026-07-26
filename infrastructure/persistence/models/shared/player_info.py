"""ORM model for tbl_player_info in sch_shared schema."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence.models.base import Base


class PlayerInfo(Base):
    """ORM model for sch_shared.tbl_player_info.

    Stores scraped biographical and contract info for each player.
    player_id is the natural PK (FBRef slug, VARCHAR(20)) — same as tbl_players.
    """

    __tablename__ = "tbl_player_info"

    player_id: Mapped[str] = mapped_column(
        String(20),
        ForeignKey(
            "sch_shared.tbl_players.player_id",
            ondelete="CASCADE",
            name="tbl_player_info_player_id_fkey",
        ),
        primary_key=True,
    )
    fk_country_birth: Mapped[str | None] = mapped_column(
        String(10),
        ForeignKey(
            "sch_shared.tbl_countries.country_id",
            ondelete="SET NULL",
            name="tbl_player_info_fk_country_birth_fkey",
        ),
        nullable=True,
    )
    fk_city: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey(
            "sch_shared.tbl_cities.city_id",
            ondelete="SET NULL",
            name="tbl_player_info_fk_city_fkey",
        ),
        nullable=True,
    )
    fk_nat_team: Mapped[str | None] = mapped_column(
        String(10),
        ForeignKey(
            "sch_shared.tbl_countries.country_id",
            ondelete="SET NULL",
            name="tbl_player_info_fk_nat_team_fkey",
        ),
        nullable=True,
    )
    fk_youth_nat_team: Mapped[str | None] = mapped_column(
        String(10),
        ForeignKey(
            "sch_shared.tbl_countries.country_id",
            ondelete="SET NULL",
            name="tbl_player_info_fk_youth_nat_team_fkey",
        ),
        nullable=True,
    )
    fk_team: Mapped[str | None] = mapped_column(
        String(8),
        ForeignKey(
            "sch_shared.tbl_teams.team_id",
            ondelete="SET NULL",
            name="tbl_player_info_fk_team_fkey",
        ),
        nullable=True,
    )
    player_born: Mapped[date | None] = mapped_column(Date, nullable=True)
    player_age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    player_height: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    player_weight: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    player_foot: Mapped[str | None] = mapped_column(String(20), nullable=True)
    fk_ply_pos_1: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey(
            "sch_shared.tbl_player_positions.position_id",
            ondelete="SET NULL",
            name="tbl_player_info_fk_ply_pos_1_fkey",
        ),
        nullable=True,
    )
    fk_ply_pos_2: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey(
            "sch_shared.tbl_player_positions.position_id",
            ondelete="SET NULL",
            name="tbl_player_info_fk_ply_pos_2_fkey",
        ),
        nullable=True,
    )
    fk_ply_pos_3: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey(
            "sch_shared.tbl_player_positions.position_id",
            ondelete="SET NULL",
            name="tbl_player_info_fk_ply_pos_3_fkey",
        ),
        nullable=True,
    )
    player_wages: Mapped[int | None] = mapped_column(Integer, nullable=True)
    player_expires: Mapped[date | None] = mapped_column(Date, nullable=True)
    player_info_url: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("ix_player_info_fk_country_birth", "fk_country_birth"),
        Index("ix_player_info_fk_city", "fk_city"),
        Index("ix_player_info_fk_nat_team", "fk_nat_team"),
        Index("ix_player_info_fk_youth_nat_team", "fk_youth_nat_team"),
        Index("ix_player_info_fk_team", "fk_team"),
        Index("ix_player_info_fk_ply_pos_1", "fk_ply_pos_1"),
        Index("ix_player_info_fk_ply_pos_2", "fk_ply_pos_2"),
        Index("ix_player_info_fk_ply_pos_3", "fk_ply_pos_3"),
        {"schema": "sch_shared"},
    )
