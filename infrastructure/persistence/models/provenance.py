"""Provenance ORM model.

Append-only audit log for completed scrape attempts. Each row is an immutable
record of one scrape outcome — no row is ever updated or deleted.

Satisfies Phase 4 requirements: native enum, 8 columns, composite + single-col
indexes, no FK to scrape_queue.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence.models.base import Base


class ProvenanceOutcome(enum.Enum):
    """Valid outcome values for a provenance row.

    DB stores label NAMES (SUCCESS/FAILURE), matching the scrapestatus pattern.
    """

    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"


class Provenance(Base):
    """ORM model for the sch_infra.provenance table.

    Columns (8):
        id            — integer primary key (auto-increment / SERIAL)
        url           — scraped URL (TEXT NOT NULL)
        scraped_at    — timestamp with time zone, server default now()
        outcome       — native Postgres enum (SUCCESS / FAILURE), NOT NULL
        content_hash  — nullable SHA256/MD5 of fetched content
        http_status   — nullable HTTP response status code
        error_message — nullable error description (populated on FAILURE)
        run_id        — nullable UUID for batch grouping (Phase 5)

    Indexes:
        ix_provenance_url_scraped_at — composite (url, scraped_at)
        ix_provenance_run_id         — single-column (run_id)
    """

    __tablename__ = "provenance"

    id: Mapped[int] = mapped_column(primary_key=True)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    scraped_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    outcome: Mapped[ProvenanceOutcome] = mapped_column(
        SAEnum(
            ProvenanceOutcome,
            native_enum=True,
            name="provenanceoutcome",
            schema="sch_infra",
        ),
        nullable=False,
    )
    content_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    http_status: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text(), nullable=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    __table_args__ = (
        Index("ix_provenance_url_scraped_at", "url", "scraped_at"),
        Index("ix_provenance_run_id", "run_id"),
        {"schema": "sch_infra"},
    )
