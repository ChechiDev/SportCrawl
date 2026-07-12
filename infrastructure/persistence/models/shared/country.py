"""ORM model for tbl_countries in sch_shared schema."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence.models.base import Base


class Country(Base):
    """ORM model for sch_shared.tbl_countries."""

    __tablename__ = "tbl_countries"

    country_id: Mapped[str] = mapped_column(String(10), primary_key=True)
    country_name: Mapped[str] = mapped_column(String(100), nullable=False)
    country_url: Mapped[str] = mapped_column(String(255), nullable=False)
    fk_conf: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("sch_shared.tbl_confederations.conf_id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("ix_countries_fk_conf", "fk_conf"),
        Index("ix_countries_country_name", "country_name"),
        {"schema": "sch_shared"},
    )
