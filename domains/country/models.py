from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class CountryRawData(BaseModel):
    country_id: str = Field(min_length=2, max_length=3)
    country_name: str = Field(min_length=1)
    country_url: str = Field(min_length=1)
    confederation: str | None = None
    flag_id: str = Field(min_length=2, max_length=2)
    flag_url: str = Field(min_length=1)

    @field_validator("confederation", mode="before")
    @classmethod
    def uppercase_confederation(cls, v: object) -> object:
        if isinstance(v, str):
            return v.upper()
        return v


class CountryPage(BaseModel):
    countries: list[CountryRawData]
