"""Domain models for club discovery scraping."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class CountrySquad(BaseModel):
    """Parsed country-squads row from the FBRef squads page.

    Fields use the natural identifiers from the HTML (country_code, flag_code)
    rather than database surrogate integers — those are resolved at persistence time.
    """

    fk_country: str = Field(min_length=2, max_length=10)
    """3-letter country code extracted from clubs_url (e.g. 'ARG')."""

    fk_flag: str | None = Field(default=None, max_length=2)
    """2-letter ISO flag code from the flag span class (e.g. 'ar')."""

    confederation: str | None = None
    """Governing body name (e.g. 'UEFA', 'CONMEBOL') — uppercased on set."""

    clubs_url: str = Field(min_length=1)
    """Full URL to the country's clubs listing on FBRef."""

    nat_team_men_url: str | None = None
    """Full URL to the men's national team history page, or None."""

    nat_team_women_url: str | None = None
    """Full URL to the women's national team history page, or None."""

    fbref_men_squad_id: str | None = Field(default=None, max_length=8)
    """8-char hex squad ID extracted from nat_team_men_url, or None."""

    fbref_women_squad_id: str | None = Field(default=None, max_length=8)
    """8-char hex squad ID extracted from nat_team_women_url, or None."""

    @field_validator("confederation", mode="before")
    @classmethod
    def _upper_conf(cls, v: object) -> object:
        return v.upper() if isinstance(v, str) else v


class CountrySquadsPage(BaseModel):
    """Collection of parsed CountrySquad rows from a single squads page fetch."""

    squads: list[CountrySquad]
