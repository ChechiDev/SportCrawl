"""ORM model for player_discovery_batch in sch_football schema."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence.models.base import FootballBase


class PlayerDiscoveryBatch(FootballBase):
    """ORM model for sch_football.player_discovery_batch.

    Tracks the total number of player URLs enqueued per country.
    country_id is the natural primary key — one batch record per country.

    FootballBase does NOT auto-apply schema; schema is declared explicitly
    in __table_args__ per project convention.
    """

    __tablename__ = "player_discovery_batch"

    country_id: Mapped[str] = mapped_column(
        String(10),
        ForeignKey(
            "sch_shared.tbl_countries.country_id",
            ondelete="CASCADE",
        ),
        primary_key=True,
    )
    total_urls: Mapped[int] = mapped_column(Integer, nullable=False)
    enqueued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = ({"schema": "sch_football"},)
