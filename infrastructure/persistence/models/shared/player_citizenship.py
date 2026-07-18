"""ORM model for tbl_player_citizenship in sch_shared schema."""

from __future__ import annotations

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence.models.base import Base


class PlayerCitizenship(Base):
    """ORM model for sch_shared.tbl_player_citizenship.

    Many-to-many between players and countries representing citizenship.
    Composite PK (player_id, country_id).
    """

    __tablename__ = "tbl_player_citizenship"

    player_id: Mapped[str] = mapped_column(
        String(20),
        ForeignKey(
            "sch_shared.tbl_players.player_id",
            ondelete="CASCADE",
            name="tbl_player_citizenship_player_id_fkey",
        ),
        primary_key=True,
    )
    country_id: Mapped[str] = mapped_column(
        String(10),
        ForeignKey(
            "sch_shared.tbl_countries.country_id",
            ondelete="RESTRICT",
            name="tbl_player_citizenship_country_id_fkey",
        ),
        primary_key=True,
    )

    __table_args__ = (
        Index("ix_player_citizenship_country_id", "country_id"),
        {"schema": "sch_shared"},
    )
