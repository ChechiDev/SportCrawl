"""ORM model for tbl_player_positions in sch_shared schema."""

from __future__ import annotations

from sqlalchemy import ForeignKey, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence.models.base import Base


class PlayerPosition(Base):
    """ORM model for sch_shared.tbl_player_positions.

    Composite primary key on (fk_player, position_code).
    Cascades deletes from tbl_players so removing a player removes all its positions.
    sort_order preserves the order positions appeared during scraping.
    """

    __tablename__ = "tbl_player_positions"

    fk_player: Mapped[str] = mapped_column(
        String(20),
        ForeignKey(
            "sch_shared.tbl_players.player_id",
            ondelete="CASCADE",
        ),
        primary_key=True,
    )
    position_code: Mapped[str] = mapped_column(String(10), primary_key=True)
    sort_order: Mapped[int] = mapped_column(SmallInteger, nullable=False)

    __table_args__ = ({"schema": "sch_shared"},)
