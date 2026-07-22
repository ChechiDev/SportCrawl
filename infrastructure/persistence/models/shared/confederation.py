"""ORM model for tbl_confederations in sch_shared schema."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence.models.base import Base


class Confederation(Base):
    """ORM model for sch_shared.tbl_confederations."""

    __tablename__ = "tbl_confederations"

    conf_id: Mapped[int] = mapped_column(primary_key=True)
    conf_name: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("conf_name", name="uq_confederations_conf_name"),
        {"schema": "sch_shared"},
    )
