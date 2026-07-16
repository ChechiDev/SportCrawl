"""ORM model for player_queue_ref in sch_infra schema."""

from __future__ import annotations

from sqlalchemy import ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence.models.base import FootballBase


class PlayerQueueRef(FootballBase):
    """ORM model for sch_infra.player_queue_ref.

    Links a scrape_queue entry to the country that owns it, enabling
    per-country progress reporting via v_player_scrape_progress.

    queue_id has a UNIQUE constraint to prevent double-counting in the view.

    FootballBase does NOT auto-apply schema; schema is declared explicitly
    in __table_args__ per project convention.
    """

    __tablename__ = "player_queue_ref"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    queue_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(
            "sch_infra.scrape_queue.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    country_id: Mapped[str] = mapped_column(
        String(10),
        ForeignKey(
            "sch_shared.tbl_countries.country_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("queue_id", name="uq_player_queue_ref_queue_id"),
        Index("ix_player_queue_ref_queue_id", "queue_id"),
        Index("ix_player_queue_ref_country_id", "country_id"),
        {"schema": "sch_infra"},
    )
