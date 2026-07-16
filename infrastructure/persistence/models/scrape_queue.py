"""ScrapeQueue ORM model.

Represents a row in the scrape_queue table that tracks URLs pending
or in-progress scraping, together with their status lifecycle.
Satisfies R8: 9 explicit columns, native enum, composite index (domain, status).
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config.settings import ScrapingSettings

from sqlalchemy import DateTime, Index, String, Text, UniqueConstraint, func, text
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

    Columns (10):
        id           — integer primary key (auto-increment)
        url          — target URL to scrape (NOT NULL)
        domain       — domain extracted from URL (NOT NULL) — used in index
        status       — native Postgres enum, defaults to PENDING
        created_at   — timestamp with time zone, default now()
        updated_at   — timestamp with time zone, default now(), auto-updated
        completed_at — nullable timestamp; set when status reaches DONE/FAILED
        error_message — nullable text; populated on FAILED
        retry_count  — integer, default 0; incremented on each retry
        locked_at    — nullable timestamp; set on IN_PROGRESS, cleared on DONE/FAILED

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
        DateTime(timezone=True),
        server_default=func.now(),
        # auto-updated by DB trigger trg_scrape_queue_updated_at
        # (migration 134f2e68682a); no ORM onupdate
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(Text(), nullable=True)
    retry_count: Mapped[int] = mapped_column(server_default=text("0"))
    # Set when status transitions to IN_PROGRESS; cleared to NULL on DONE/FAILED.
    # recover_stale() uses this to reset rows stuck in IN_PROGRESS beyond the TTL.
    locked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Discriminates queue entries by scraping job (e.g. 'player_discovery').
    job_type: Mapped[str | None] = mapped_column(String(50), nullable=True)

    __table_args__ = (
        UniqueConstraint("url", name="uq_scrape_queue_url"),
        Index("ix_scrape_queue_domain_status", "domain", "status"),
        {"schema": "sch_infra"},
    )

    @classmethod
    def from_url(
        cls, url: str, *, settings: ScrapingSettings | None = None
    ) -> ScrapeQueue:
        """Factory: create a new ScrapeQueue row from a URL with SSRF validation.

        Derives domain via validate_scrape_url. Raises SSRFError if the URL
        fails scheme, allowlist, or private-IP checks.
        """
        from config.settings import ScrapingSettings as _ScrapingSettings
        from core.security.url_validator import validate_scrape_url

        cfg = settings or _ScrapingSettings()
        domain = validate_scrape_url(url, cfg.allowed_hosts)
        return cls(domain=domain, url=url, status=ScrapeStatus.PENDING)
