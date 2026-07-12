"""ORM model for tbl_flags in sch_shared schema."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence.models.base import Base


class Flag(Base):
    """ORM model for sch_shared.tbl_flags."""

    __tablename__ = "tbl_flags"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    flag_id: Mapped[str] = mapped_column(String(2), nullable=False)
    flag_url: Mapped[str] = mapped_column(String(500), nullable=False)
    fk_country: Mapped[str] = mapped_column(
        String(10),
        ForeignKey("sch_shared.tbl_countries.country_id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("fk_country", name="uq_flags_fk_country"),
        Index("ix_flags_flag_id", "flag_id"),
        {"schema": "sch_shared"},
    )
