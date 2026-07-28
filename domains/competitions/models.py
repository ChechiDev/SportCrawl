from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CompetitionRawData:
    comp_id: int
    comp_name: str
    comp_url: str
    comp_type_name: str
    gender: str
    conf_name: str | None
    flag_id: str | None
    country_id: str | None
    first_season: int | None
    last_season: int | None


@dataclass
class CompetitionsPage:
    competitions: list[CompetitionRawData]
