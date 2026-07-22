"""ORM model for tbl_competition in sch_shared schema."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence.models.base import Base


class Competition(Base):
    """ORM model for sch_shared.tbl_competition."""

    __tablename__ = "tbl_competition"

    comp_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    comp_name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("comp_name", name="uq_tbl_competition_comp_name"),
        {"schema": "sch_shared"},
    )
