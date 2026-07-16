"""Pure Pydantic domain models for the player discovery domain.

No SQLAlchemy imports. No infrastructure dependencies.
"""

from __future__ import annotations

from pydantic import BaseModel


class PlayerRawData(BaseModel):
    """Raw player data scraped from a FBRef country player-list page.

    Attributes:
        player_id: 8-character FBRef slug (e.g. "d70ce98e").
        full_name: Player name as displayed on the page
            (never None — parser always fills it).
        career_start: Year the player's professional career began.
        career_end: Year the career ended; equals career_start
            for currently active players.
        player_url: Absolute URL to the player's FBRef profile page.
    """

    player_id: str
    full_name: str
    career_start: int
    career_end: int  # equals career_start for active players
    player_url: str


class PlayerListPage(BaseModel):
    """Aggregated result of scraping one FBRef country player-list page.

    Attributes:
        country_id: FBRef country code (e.g. "ARG", "ESP").
        players: All players found on the page, in scrape order.
    """

    country_id: str
    players: list[PlayerRawData]
