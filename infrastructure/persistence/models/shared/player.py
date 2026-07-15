"""ORM model for tbl_players in sch_shared schema."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, SmallInteger, String, func
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence.models.base import Base


class Player(Base):
    """ORM model for sch_shared.tbl_players.

    player_id is the natural primary key — an 8-char FBRef slug (e.g. 'd70ce98e');
    VARCHAR(20) for forward compatibility. No surrogate id is used; FKs from
    queue refs target player_id directly.

    Columns: player_id, full_name, fk_country, career_start, career_end,
    player_url, created_at, updated_at.
    """

    __tablename__ = "tbl_players"

    player_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    fk_country: Mapped[str | None] = mapped_column(
        String(10),
        ForeignKey(
            "sch_shared.tbl_countries.country_id",
            ondelete="SET NULL",
            name="tbl_players_fk_country_fkey",
        ),
        nullable=True,
    )
    career_start: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    career_end: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    player_url: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("ix_players_fk_country", "fk_country"),
        {"schema": "sch_shared"},
    )
