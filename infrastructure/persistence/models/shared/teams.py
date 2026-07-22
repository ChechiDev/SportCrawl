"""ORM model for tbl_teams in sch_shared schema."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKeyConstraint, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence.models.base import Base


class Teams(Base):
    """ORM model for sch_shared.tbl_teams.

    Each row represents one team/club with its primary competition, active
    seasons range, and gender. Upsert target keyed on team_id (natural PK
    from FBRef squad URL).
    """

    __tablename__ = "tbl_teams"

    team_id: Mapped[str] = mapped_column(String(8), primary_key=True)
    team_name: Mapped[str] = mapped_column(String(200), nullable=False)
    fk_country: Mapped[str] = mapped_column(String(10), nullable=False)
    fk_gender: Mapped[int] = mapped_column(Integer, nullable=False)
    fk_comp: Mapped[int | None] = mapped_column(Integer, nullable=True)
    team_from: Mapped[int | None] = mapped_column(Integer, nullable=True)
    team_to: Mapped[int | None] = mapped_column(Integer, nullable=True)
    team_url: Mapped[str] = mapped_column(String(500), nullable=False)
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
        ForeignKeyConstraint(
            ["fk_country"],
            ["sch_shared.tbl_countries.country_id"],
            name="fk_tbl_teams_country",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["fk_gender"],
            ["sch_shared.tbl_gender.id"],
            name="fk_tbl_teams_gender",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["fk_comp"],
            ["sch_shared.tbl_competition.comp_id"],
            name="fk_tbl_teams_comp",
            ondelete="SET NULL",
        ),
        Index("ix_tbl_teams_fk_country", "fk_country"),
        Index("ix_tbl_teams_fk_gender", "fk_gender"),
        Index("ix_tbl_teams_fk_comp", "fk_comp"),
        {"schema": "sch_shared"},
    )
