"""ORM model for tbl_competition_urls in sch_fbref_backend schema."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence.models.base import BackendBase


class CompetitionUrl(BackendBase):
    """ORM model for sch_fbref_backend.tbl_competition_urls.

    Tracks scraping URLs per competition with scheduling metadata.
    One row per (competition, url_type) combination.
    """

    __tablename__ = "tbl_competition_urls"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    fk_comp: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(
            "sch_fbref_shared.tbl_competition.comp_id",
            ondelete="CASCADE",
            name="tbl_competition_urls_fk_comp_fkey",
        ),
        nullable=False,
    )
    url_type: Mapped[str] = mapped_column(String(50), nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="PENDING"
    )
    cadence_hours: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="168"
    )
    last_scraped_at: Mapped[datetime | None] = mapped_column(nullable=True)
    next_scrape_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=text("now()")
    )
    last_scrape_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    priority: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="5")
    retry_count: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="0"
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("fk_comp", "url_type", name="uq_competition_urls_comp_url_type"),
        CheckConstraint("priority BETWEEN 1 AND 10", name="ck_competition_urls_priority"),
        CheckConstraint("cadence_hours > 0", name="ck_competition_urls_cadence_hours"),
        CheckConstraint("retry_count >= 0", name="ck_competition_urls_retry_count"),
        Index(
            "ix_competition_urls_due",
            "next_scrape_at",
            "priority",
            postgresql_where=text("status = 'ACTIVE'"),
        ),
        Index("ix_competition_urls_fk_comp", "fk_comp"),
        Index("ix_competition_urls_status", "status"),
        {"schema": "sch_fbref_backend"},
    )
