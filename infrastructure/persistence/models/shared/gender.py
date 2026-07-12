"""ORM model for tbl_gender in sch_shared schema."""

from __future__ import annotations

from sqlalchemy import String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence.models.base import Base


class Gender(Base):
    """ORM model for sch_shared.tbl_gender."""

    __tablename__ = "tbl_gender"

    id: Mapped[int] = mapped_column(primary_key=True)
    gender: Mapped[str] = mapped_column(String(1), nullable=False)

    __table_args__ = (
        UniqueConstraint("gender", name="uq_gender_gender"),
        {"schema": "sch_shared"},
    )
