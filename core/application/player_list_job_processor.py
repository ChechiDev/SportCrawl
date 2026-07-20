"""PlayerListJobProcessor — wraps PlayerListScraper.scrape() + mark_done.

ADR-3: Unlike ScrapeJobProcessor (which swallows errors and marks failed
internally), PlayerListJobProcessor re-raises all exceptions. The worker that
calls this processor owns retry/restart classification (BrowserException vs
generic) and mark_failed, because BrowserException must trigger a browser
restart — a concern the processor cannot signal via a simple return value.
These two processors have intentionally different error contracts and must NOT
be treated as structurally equivalent.
"""

from __future__ import annotations

from infrastructure.persistence.repositories.player_list_queue import (
    PlayerListQueueRepository,
)
from infrastructure.scraping.players import PlayerListScraper


class PlayerListJobProcessor:
    """Processes a single player-list job: scrape then mark done.

    The caller (worker) is responsible for:
    - Opening and committing the DB session used by queue_repo.
    - Calling mark_failed and deciding whether to restart the browser on error.
    """

    def __init__(
        self,
        scraper: PlayerListScraper,
        queue_repo: PlayerListQueueRepository,
    ) -> None:
        self._scraper = scraper
        self._queue_repo = queue_repo

    async def process(self, job: object) -> tuple[bool, int]:
        """Scrape job.url and mark the job done.

        Returns:
            (True, total_players) on success.

        Raises:
            Any exception from scraper or queue_repo — caller owns handling.
        """
        page, _ = await self._scraper.scrape(job.url)  # type: ignore[union-attr]
        await self._queue_repo.mark_done(job.id)  # type: ignore[union-attr]
        return True, len(page.players)
