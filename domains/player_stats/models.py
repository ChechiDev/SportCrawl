"""Pure Pydantic domain models for the player stats domain.

No SQLAlchemy imports. No infrastructure dependencies.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel


class PlayerStdStatsRawData(BaseModel):
    player_id: str
    season: int
    fk_team: str
    fk_country: str | None = None
    fk_comp: int
    age: int = 0
    matches: int = 0
    starts: int = 0
    minutes: int = 0
    min_per_90: Decimal = Decimal("0.00")
    goals: int = 0
    assists: int = 0
    goals_assists: int = 0
    goals_pk: int = 0
    pk_scored: int = 0
    pk_att: int = 0
    yellow_cards: int = 0
    red_cards: int = 0
    goals_p90: Decimal = Decimal("0.00")
    assists_p90: Decimal = Decimal("0.00")
    goals_assists_p90: Decimal = Decimal("0.00")
    goals_pk_p90: Decimal = Decimal("0.00")
    goals_assists_pk_p90: Decimal = Decimal("0.00")
    team_url: str | None = None
    comp_id: int | None = None
    match_url: str | None = None
    comp_name: str = ""


class PlayerShootingStatsRawData(BaseModel):
    """Raw shooting stats data scraped from a FBRef player profile page.

    fk_comp is initially set to 0 and resolved by the repository layer
    via a comp_name upsert into tbl_competition.
    """

    player_id: str
    season: int
    fk_team: str
    fk_country: str | None = None
    fk_comp: int
    min_per_90: Decimal = Decimal("0.00")
    goals: int = 0
    shots: int = 0
    shots_on_target: int = 0
    shots_on_target_pct: Decimal = Decimal("0.00")
    shots_per_90: Decimal = Decimal("0.00")
    sot_per_90: Decimal = Decimal("0.00")
    goals_per_shot: Decimal = Decimal("0.00")
    goals_per_sot: Decimal = Decimal("0.00")
    pk_scored: int = 0
    pk_att: int = 0
    team_url: str | None = None
    comp_id: int | None = None
    match_url: str | None = None
    comp_name: str = ""


class PlayerPlayingTimeStatsRawData(BaseModel):
    """Raw playing time stats data scraped from a FBRef player profile page.

    fk_comp is initially set to 0 and resolved by the repository layer
    via a comp_name upsert into tbl_competition.
    """

    player_id: str
    season: int
    fk_team: str
    fk_country: str | None = None
    fk_comp: int
    matches: int = 0
    minutes: int = 0
    min_per_match: Decimal = Decimal("0.00")
    min_pct: Decimal = Decimal("0.00")
    min_per_90: Decimal = Decimal("0.00")
    starts: int = 0
    min_per_start: Decimal = Decimal("0.00")
    games_complete: int = 0
    subs: int = 0
    min_per_sub: Decimal = Decimal("0.00")
    unused_sub: int = 0
    ppm: Decimal = Decimal("0.00")
    on_goals_for: int = 0
    on_goals_against: int = 0
    plus_minus: int = 0
    plus_minus_per90: Decimal = Decimal("0.00")
    on_off: Decimal = Decimal("0.00")
    team_url: str | None = None
    comp_id: int | None = None
    match_url: str | None = None
    comp_name: str = ""


class PlayerMiscStatsRawData(BaseModel):
    """Raw miscellaneous stats data scraped from a FBRef player profile page.

    fk_comp is initially set to 0 and resolved by the repository layer
    via a comp_name upsert into tbl_competition.
    """

    player_id: str
    season: int
    fk_team: str
    fk_country: str | None = None
    fk_comp: int
    min_per_90: Decimal = Decimal("0.00")
    yellow_cards: int = 0
    red_cards: int = 0
    yellow_red_cards: int = 0
    fouls: int = 0
    fouled: int = 0
    offsides: int = 0
    crosses: int = 0
    interceptions: int = 0
    tackles_won: int = 0
    pk_won: int = 0
    pk_conceded: int = 0
    own_goals: int = 0
    team_url: str | None = None
    comp_id: int | None = None
    match_url: str | None = None
    comp_name: str = ""
