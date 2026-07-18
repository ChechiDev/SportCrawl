"""Pure Pydantic domain models for the player info domain.

No SQLAlchemy imports. No infrastructure dependencies.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class PlayerInfoRawData(BaseModel):
    """Raw player info data scraped from a FBRef player profile page.

    All fields except player_id and player_info_url are optional (None by default).
    player_wages=0 is a valid value meaning wages are explicitly zero — not unknown.
    player_age is intentionally absent: age is derived at read time
        via AGE(player_born).

    Attributes:
        player_id: FBRef slug (e.g. "abc123"), 8 chars typically.
        full_name: Player display name from the page <h1> heading.
        fk_country_birth: country_id FK referencing tbl_countries (e.g. "ARG").
        country_birth_name: Raw country name extracted from the born paragraph text.
        national_team_name: Raw national team country name from the National Team link.
        fk_national_team: country_id FK resolved from national_team_name.
        city_name: Free-text birth city name; no FK.
        player_born: Date of birth.
        player_height: Height in centimetres.
        player_weight: Weight in kilograms.
        position_1: Primary position code (e.g. "FW").
        position_2: Secondary position code.
        position_3: Tertiary position code.
        player_foot: Preferred foot (e.g. "Left", "Right").
        player_wages: Weekly wages in local currency; 0 is valid, None means unknown.
        player_expires: Contract expiry date.
        player_info_url: Absolute URL to the FBRef player profile page.
        photo_url: Absolute URL to the player's photo; None when absent.
    """

    player_id: str
    full_name: str | None = None
    fk_country_birth: str | None = None
    country_birth_name: str | None = None
    national_team_name: str | None = None
    fk_national_team: str | None = None
    city_name: str | None = None
    player_born: date | None = None
    player_height: int | None = None
    player_weight: int | None = None
    position_1: str | None = None
    position_2: str | None = None
    position_3: str | None = None
    player_foot: str | None = None
    player_wages: int | None = None
    player_expires: date | None = None
    player_info_url: str
    photo_url: str | None = None
    citizenship_name: str | None = None
    youth_nat_team_name: str | None = None
    club_name: str | None = None
    club_url: str | None = None
    fk_citizenship: str | None = None
    fk_youth_nat_team: str | None = None


class PlayerInfoPage(BaseModel):
    """Aggregated result of scraping one or more FBRef player profile pages.

    Attributes:
        players: List of PlayerInfoRawData scraped from profile pages.
    """

    players: list[PlayerInfoRawData]
