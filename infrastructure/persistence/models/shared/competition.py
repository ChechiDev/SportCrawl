from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import DateTime, ForeignKey, Integer, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence.models.base import Base


class Competition(Base):
    __tablename__ = "tbl_competition"

    comp_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=False, default=None
    )
    comp_name: Mapped[str] = mapped_column(String(200), nullable=False)
    fk_comp_type: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("sch_fbref_shared.tbl_comp_type.comp_type_id", ondelete="RESTRICT"),
        nullable=False,
    )
    fk_gender: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("sch_fbref_shared.tbl_gender.id", ondelete="RESTRICT"),
        nullable=False,
    )
    fk_conf: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("sch_fbref_shared.tbl_confederations.conf_id", ondelete="RESTRICT"),
        nullable=True,
    )
    fk_flag: Mapped[str | None] = mapped_column(
        String(3),
        ForeignKey("sch_fbref_shared.tbl_flags.flag_id", ondelete="SET NULL"),
        nullable=True,
    )
    fk_country: Mapped[str | None] = mapped_column(
        String(10),
        ForeignKey("sch_fbref_shared.tbl_countries.country_id", ondelete="SET NULL"),
        nullable=True,
    )
    first_season: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    last_season: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    comp_url: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    __table_args__ = (
        sa.Index("ix_tbl_competition_fk_comp_type", "fk_comp_type"),
        sa.Index("ix_tbl_competition_fk_gender", "fk_gender"),
        {"schema": "sch_fbref_shared"},
    )
