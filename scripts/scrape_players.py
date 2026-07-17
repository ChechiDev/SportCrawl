"""Player discovery scraper — single country or all countries.

Usage:
    uv run python scripts/scrape_players.py                  # Spain (default)
    uv run python scripts/scrape_players.py --country ARG
    uv run python scripts/scrape_players.py --url <FBREF_COUNTRY_PLAYERS_URL>
    uv run python scripts/scrape_players.py --all            # all 219 countries from DB
"""

from __future__ import annotations

import argparse
import asyncio
import logging

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config.settings import Settings
from core.exceptions.scraper import PageLoadError, RateLimitError
from infrastructure.browser.pydoll_engine import PydollEngine
from infrastructure.persistence.models.shared.country import Country
from infrastructure.persistence.session import create_session_factory, get_session
from infrastructure.scraping.players import PlayerListScraper

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

_FBREF_BASE = "https://fbref.com"
_BASE_URL = "https://fbref.com/en/country/players/{code}/{code}-Football"

COUNTRY_URLS: dict[str, str] = {
    "ESP": "https://fbref.com/en/country/players/ESP/Spain-Football",
    "ARG": "https://fbref.com/en/country/players/ARG/Argentina-Football",
    "BRA": "https://fbref.com/en/country/players/BRA/Brazil-Football",
    "FRA": "https://fbref.com/en/country/players/FRA/France-Football",
    "ENG": "https://fbref.com/en/country/players/ENG/England-Football",
}


def _players_url(country_url: str) -> str:
    """Derive player-list URL from country_url stored in DB.

    /en/country/AFG/Afghanistan-Football
    → https://fbref.com/en/country/players/AFG/Afghanistan-Football
    """
    path = country_url.replace("/en/country/", "/en/country/players/", 1)
    return f"{_FBREF_BASE}{path}"


async def _load_all_countries(
    session_factory: async_sessionmaker[AsyncSession],
) -> list[tuple[str, str]]:
    """Return (country_id, player_list_url) for every country in the DB."""
    async with get_session(session_factory) as session:
        result = await session.execute(
            sa.select(Country.country_id, Country.country_url)
            .order_by(Country.country_name)
        )
        return [(row.country_id, _players_url(row.country_url)) for row in result]


async def scrape_one(scraper: PlayerListScraper, url: str) -> int:
    page = await scraper.scrape(url)
    return len(page.players)


async def main_single(url: str, verbose: bool = True) -> int:
    settings = Settings()  # type: ignore[call-arg]
    session_factory = create_session_factory(settings.db)
    async with PydollEngine() as engine:
        scraper = PlayerListScraper(engine, settings.scraping, session_factory)
        page = await scraper.scrape(url)
        count = len(page.players)

        if verbose:
            print(f"\ncountry_id : {page.country_id}")
            print(f"players    : {count}")
            print("\nFirst 10:")
            for p in page.players[:10]:
                career = f"{p.career_start}–{p.career_end}"
                print(f"  {p.player_id}  {p.full_name:<30}  {career}")

        return count


async def main_all() -> None:
    settings = Settings()  # type: ignore[call-arg]
    session_factory = create_session_factory(settings.db)
    countries = await _load_all_countries(session_factory)
    total = len(countries)
    print(f"Scraping {total} countries…\n")

    grand_total = 0
    failed: list[str] = []

    async with PydollEngine() as engine:
        scraper = PlayerListScraper(engine, settings.scraping, session_factory)

        for i, (country_id, url) in enumerate(countries, 1):
            try:
                count = await scrape_one(scraper, url)
                grand_total += count
                total_str = f"{grand_total:,}"
                prefix = f"[{i:>3}/{total}] {country_id:<6}"
                print(f"{prefix}  {count:>5} players  (total: {total_str})")
            except (PageLoadError, RateLimitError) as exc:
                failed.append(country_id)
                print(f"[{i:>3}/{total}] {country_id:<6}  ERROR: {exc}")

    print(f"\nDone. {grand_total:,} players across {total - len(failed)} countries.")
    if failed:
        print(f"Failed ({len(failed)}): {', '.join(failed)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape FBRef player lists.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--country",
        metavar="CODE",
        default="ESP",
        help="FBRef country code (default: ESP).",
    )
    group.add_argument(
        "--url", metavar="URL", help="Full FBRef country player-list URL."
    )
    group.add_argument("--all", action="store_true", dest="all_countries",
                       help="Scrape all countries from the database.")
    args = parser.parse_args()

    if args.all_countries:
        asyncio.run(main_all())
    else:
        target_url = args.url or COUNTRY_URLS.get(
            args.country.upper(),
            _BASE_URL.format(code=args.country.upper()),
        )
        asyncio.run(main_single(target_url))


if __name__ == "__main__":
    main()
