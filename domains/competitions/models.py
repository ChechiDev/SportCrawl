from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CompetitionRawData:
    comp_id: int
    comp_name: str
    comp_url: str
    """Full URL to the competition's FBRef index page.
    Python-only field — not persisted to tbl_competition (dropped in p50a).
    Used only to co-insert into sch_fbref_backend.tbl_competition_urls."""
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
