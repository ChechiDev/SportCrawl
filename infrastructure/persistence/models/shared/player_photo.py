"""ORM model for tbl_player_photo in sch_shared schema."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence.models.base import Base


class PlayerPhoto(Base):
    """ORM model for sch_shared.tbl_player_photo.

    One row per player; a row is only inserted when a photo URL was found.
    player_id is the natural PK (FBRef slug), FK → tbl_players.player_id.
    UNIQUE(player_id) is enforced via the primary key constraint.
    """

    __tablename__ = "tbl_player_photo"

    player_id: Mapped[str] = mapped_column(
        String(20),
        ForeignKey(
            "sch_shared.tbl_players.player_id",
            ondelete="CASCADE",
            name="tbl_player_photo_player_id_fkey",
        ),
        primary_key=True,
    )
    player_photo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = ({"schema": "sch_shared"},)
