from __future__ import annotations

from sqlalchemy import Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence.models.base import Base


class CompType(Base):
    __tablename__ = "tbl_comp_type"

    comp_type_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    comp_type_name: Mapped[str] = mapped_column(String(100), nullable=False)

    __table_args__ = (
        UniqueConstraint("comp_type_name", name="uq_tbl_comp_type_comp_type_name"),
        {"schema": "sch_fbref_shared"},
    )
