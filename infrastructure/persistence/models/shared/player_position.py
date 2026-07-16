"""ORM model for tbl_player_positions in sch_shared schema."""

from __future__ import annotations

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence.models.base import Base


class PlayerPosition(Base):
    """ORM model for sch_shared.tbl_player_positions.

    Lookup table of known position codes (e.g. "FW", "MF", "DF", "GK").
    Populated by Phase 14 (player-info scraping). No FK relationships to tbl_players
    in the current schema.
    """

    __tablename__ = "tbl_player_positions"

    position_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    position_code: Mapped[str] = mapped_column(String(10), unique=True, nullable=False)

    __table_args__ = ({"schema": "sch_shared"},)
