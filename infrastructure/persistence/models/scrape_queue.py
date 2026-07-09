"""ScrapeQueue ORM model.

Represents a row in the scrape_queue table that tracks URLs pending
or in-progress scraping, together with their status lifecycle.
Satisfies R8: 9 explicit columns, native enum, composite index (domain, status).
"""

import enum
from datetime import datetime

from sqlalchemy import DateTime, Index, Text, UniqueConstraint, func, text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence.models.base import Base


class ScrapeStatus(enum.Enum):
    """Valid status values for a scrape_queue row.

    Transitions: PENDING → IN_PROGRESS → DONE | FAILED
    Retry path:  FAILED  → PENDING  (only via explicit retry logic)
    """

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    FAILED = "failed"


class ScrapeQueue(Base):
    """ORM model for the scrape_queue table.

    Columns (9):
        id           — integer primary key (auto-increment)
        url          — target URL to scrape (NOT NULL)
        domain       — domain extracted from URL (NOT NULL) — used in index
        status       — native Postgres enum, defaults to PENDING
        created_at   — timestamp with time zone, default now()
        updated_at   — timestamp with time zone, default now(), auto-updated
        completed_at — nullable timestamp; set when status reaches DONE/FAILED
        error_message — nullable text; populated on FAILED
        retry_count  — integer, default 0; incremented on each retry

    Indexes:
        ix_scrape_queue_domain_status — composite (domain, status)
    """

    __tablename__ = "scrape_queue"

    id: Mapped[int] = mapped_column(primary_key=True)
    url: Mapped[str] = mapped_column(Text())
    domain: Mapped[str] = mapped_column(Text())
    # DB stores enum label names (PENDING, not "pending"); .value is Python-side only.
    status: Mapped[ScrapeStatus] = mapped_column(
        SAEnum(ScrapeStatus, native_enum=True, name="scrapestatus", schema="sch_infra"),
        server_default=text("'PENDING'"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_message: Mapped[str | None]
    retry_count: Mapped[int] = mapped_column(server_default=text("0"))

    __table_args__ = (
        UniqueConstraint("url", name="uq_scrape_queue_url"),
        Index("ix_scrape_queue_domain_status", "domain", "status"),
        {"schema": "sch_infra"},
    )

    @classmethod
    def from_url(cls, domain: str, url: str) -> "ScrapeQueue":
        """Factory: create a new ScrapeQueue row with status=PENDING."""
        return cls(domain=domain, url=url, status=ScrapeStatus.PENDING)
