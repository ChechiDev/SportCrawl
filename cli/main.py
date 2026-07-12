"""CLI entry point for sportcrawl.

Commands:
- work-server: start the aiohttp work server with a shared JobLoop event loop.
- scrape-players: discover and persist players for one country or all countries.
"""

from __future__ import annotations

import asyncio

import typer

from config.settings import Settings
from infrastructure.work_server.runtime import serve

app = typer.Typer(name="sportcrawl", help="Sportcrawl CLI")


@app.command("work-server")
def work_server() -> None:
    """Start the aiohttp work server and JobLoop in a single process."""
    settings = Settings()  # type: ignore[call-arg]
    asyncio.run(serve(settings))


@app.command("scrape-players")
def scrape_players(
    country: str | None = typer.Option(None, "--country", "-c", metavar="CODE",
                                       help="FBRef country code, e.g. ARG."),
    url: str | None = typer.Option(None, "--url", "-u", metavar="URL",
                                   help="Full FBRef country player-list URL."),
    all_countries: bool = typer.Option(False, "--all", "-a",
                                        help="Scrape all countries from the database."),
) -> None:
    """Discover and persist players for one country or all countries."""
    import logging
    logging.getLogger("pydoll").setLevel(logging.WARNING)
    logging.getLogger("infrastructure.browser").setLevel(logging.WARNING)
    logging.getLogger("infrastructure.scraping").setLevel(logging.WARNING)

    from scripts.scrape_players import main_all, main_single

    _FBREF_BASE = "https://fbref.com/en/country/players"

    if all_countries:
        asyncio.run(main_all())
    elif url:
        asyncio.run(main_single(url))
    elif country:
        asyncio.run(main_single(f"{_FBREF_BASE}/{country.upper()}/{country.upper()}-Football"))
    else:
        typer.echo("Specify --country, --url, or --all.", err=True)
        raise typer.Exit(code=1)


def main() -> None:
    """Run the CLI."""
    app()
