from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field, field_validator


class CountryRawData(BaseModel):
    country_id: str = Field(min_length=2, max_length=3)
    country_name: str = Field(min_length=1)
    country_url: str = Field(min_length=1)
    confederation: str | None = None
    flag_id: str | None = Field(default=None, min_length=2, max_length=3)
    flag_url: str | None = None

    @field_validator("confederation", mode="before")
    @classmethod
    def uppercase_confederation(cls, v: object) -> object:
        if isinstance(v, str):
            return v.upper()
        return v


class CountryPage(BaseModel):
    countries: list[CountryRawData]


@dataclass
class CountryPlayersRawData:
    country_name: str
    players_url: str
    country_id: str | None = None


@dataclass
class CountryPlayersPage:
    entries: list[CountryPlayersRawData]
