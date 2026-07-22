"""ORM model for tbl_country_squads in sch_shared schema."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence.models.base import Base


class CountrySquads(Base):
    """ORM model for sch_shared.tbl_country_squads.

    Natural PK on fk_country (one row per country). Upsert target for the
    club-discovery scraper.
    """

    __tablename__ = "tbl_country_squads"

    fk_country: Mapped[str] = mapped_column(
        String(10),
        ForeignKey("sch_shared.tbl_countries.country_id", ondelete="CASCADE"),
        primary_key=True,
    )
    fk_flag: Mapped[str | None] = mapped_column(
        String(2),
        ForeignKey("sch_shared.tbl_flags.flag_id", ondelete="SET NULL"),
        nullable=True,
    )
    clubs_url: Mapped[str] = mapped_column(String(500), nullable=False)
    nat_team_men_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    nat_team_women_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    fbref_men_squad_id: Mapped[str | None] = mapped_column(String(8), nullable=True)
    fbref_women_squad_id: Mapped[str | None] = mapped_column(String(8), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_country_squads_fk_flag", "fk_flag"),
        Index("ix_country_squads_men_squad_id", "fbref_men_squad_id"),
        Index("ix_country_squads_women_squad_id", "fbref_women_squad_id"),
        {"schema": "sch_shared"},
    )
