"""ORM model for tbl_cities in sch_fbref_shared schema."""

from __future__ import annotations

from sqlalchemy import Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence.models.base import Base


class City(Base):
    """ORM model for sch_fbref_shared.tbl_cities.

    Lookup table for birth cities referenced by tbl_player_info.
    city_id is a surrogate PK; city_name must be unique.
    """

    __tablename__ = "tbl_cities"

    city_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    city_name: Mapped[str] = mapped_column(String(150), nullable=False)

    __table_args__ = (
        UniqueConstraint("city_name", name="uq_tbl_cities_city_name"),
        {"schema": "sch_fbref_shared"},
    )
