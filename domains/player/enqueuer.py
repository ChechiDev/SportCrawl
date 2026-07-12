"""Player discovery enqueuer — pure domain coordinator.

No SQLAlchemy imports. No infrastructure dependencies.
The concrete repository is injected at runtime via the DiscoveryRepo Protocol.
"""

from __future__ import annotations

from typing import Protocol

from domains.player.models import PlayerListPage, PlayerRawData


class DiscoveryRepo(Protocol):
    """Structural protocol for the player discovery repository.

    This is a public DI contract; implementations must live in infrastructure
    and are injected at runtime.
    """

    async def bulk_enqueue(self, rows: list[PlayerRawData], country_id: str) -> int:
        """Persist player rows and enqueue scrape URLs; return the enqueued count."""
        ...


class PlayerDiscoveryEnqueuer:
    """Coordinates player discovery: delegates persistence and enqueueing to the repo.

    This class lives in the domain layer and must remain free of SQLAlchemy imports.
    """

    def __init__(self, repo: DiscoveryRepo) -> None:
        self._repo = repo

    async def enqueue(self, page: PlayerListPage) -> int:
        """Enqueue all players from a scraped page.

        Args:
            page: Parsed country player-list page; country_id taken from
                page.country_id.

        Returns:
            Number of player URLs enqueued (as reported by the repository).
        """
        return await self._repo.bulk_enqueue(page.players, page.country_id)
