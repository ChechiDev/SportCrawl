"""Unit tests for PlayerDiscoveryEnqueuer domain class."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from domains.player.enqueuer import PlayerDiscoveryEnqueuer
from domains.player.models import PlayerListPage, PlayerRawData

_PLAYER_URL = "https://fbref.com/en/players/d70ce98e/Lionel-Messi"
_PLAYER_URL_2 = "https://fbref.com/en/players/abc12345/Some-Player"


def _make_player(player_id: str, player_url: str) -> PlayerRawData:
    return PlayerRawData(
        player_id=player_id,
        display_name="Test Player",
        full_name=None,
        career_start=2000,
        career_end=None,
        positions=["FW"],
        player_url=player_url,
    )


# ---------------------------------------------------------------------------
# PlayerDiscoveryEnqueuer.enqueue — delegates to repo using page.country_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enqueue_calls_bulk_enqueue_with_players_and_country_id() -> None:
    """enqueue(page) calls repo.bulk_enqueue using page.country_id (no extra arg)."""
    players = [
        _make_player("d70ce98e", _PLAYER_URL),
        _make_player("abc12345", _PLAYER_URL_2),
    ]
    page = PlayerListPage(country_id="ARG", players=players)

    repo = MagicMock()
    repo.bulk_enqueue = AsyncMock(return_value=2)

    enqueuer = PlayerDiscoveryEnqueuer(repo=repo)
    result = await enqueuer.enqueue(page)

    repo.bulk_enqueue.assert_called_once_with(players, "ARG")
    assert result == 2


@pytest.mark.asyncio
async def test_enqueue_returns_count_from_repo() -> None:
    """enqueue(page) must return exactly the int returned by repo.bulk_enqueue."""
    players = [_make_player("d70ce98e", _PLAYER_URL)]
    page = PlayerListPage(country_id="ESP", players=players)

    repo = MagicMock()
    repo.bulk_enqueue = AsyncMock(return_value=50)

    enqueuer = PlayerDiscoveryEnqueuer(repo=repo)
    result = await enqueuer.enqueue(page)

    assert result == 50


@pytest.mark.asyncio
async def test_enqueue_empty_page_calls_bulk_enqueue_with_empty_list() -> None:
    """enqueue(page) with no players calls bulk_enqueue with empty list."""
    page = PlayerListPage(country_id="BRA", players=[])

    repo = MagicMock()
    repo.bulk_enqueue = AsyncMock(return_value=0)

    enqueuer = PlayerDiscoveryEnqueuer(repo=repo)
    result = await enqueuer.enqueue(page)

    repo.bulk_enqueue.assert_called_once_with([], "BRA")
    assert result == 0
