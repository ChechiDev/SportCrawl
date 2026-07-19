"""CLI entry point for sportcrawl.

Commands:
- work-server: start the aiohttp work server with a shared JobLoop event loop.
- scrape-players: discover and persist players for one country or all countries.
"""

from __future__ import annotations

import asyncio

import typer

from cli.players import players_app
from config.settings import Settings
from infrastructure.work_server.runtime import serve

app = typer.Typer(name="sportcrawl", help="Sportcrawl CLI")
app.add_typer(players_app, name="players")


@app.command("work-server")
def work_server() -> None:
    """Start the aiohttp work server and JobLoop in a single process."""
    settings = Settings()  # type: ignore[call-arg]
    asyncio.run(serve(settings))


@app.command("scrape-players")
def scrape_players(
    country: str | None = typer.Option(
        None, "--country", "-c", metavar="CODE",
        help="FBRef country code, e.g. ARG.",
    ),
    url: str | None = typer.Option(
        None, "--url", "-u", metavar="URL",
        help="Full FBRef country player-list URL.",
    ),
    all_countries: bool = typer.Option(
        False, "--all", "-a",
        help="Scrape all countries from the database.",
    ),
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
        code = country.upper()
        asyncio.run(main_single(f"{_FBREF_BASE}/{code}/{code}-Football"))
    else:
        typer.echo("Specify --country, --url, or --all.", err=True)
        raise typer.Exit(code=1)


@app.command("pipeline")
def pipeline(
    workers: int = typer.Option(
        1, "--workers", "-w",
        help="Number of parallel workers per step (default: 1).",
    ),
    trigger_count: int = typer.Option(
        100, "--trigger-count",
        help="Minimum players in DB before Step 3 starts (default: 100).",
    ),
) -> None:
    """Run Step 2 (players) and Step 3 (player info) concurrently."""
    from scripts.scrape_pipeline import main as pipeline_main

    asyncio.run(pipeline_main(
        workers=workers,
        trigger_count=trigger_count,
    ))


@app.command("reset")
def reset_db(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
) -> None:
    """Truncate all scraped data. Keeps schemas and migrations intact."""
    from rich.console import Console
    from rich.panel import Panel

    console = Console()

    console.print(Panel(
        "[bold red]WARNING[/bold red]\n\n"
        "This will delete ALL scraped data:\n"
        "  • sch_shared: countries, players, player_info, photos, positions\n"
        "  • sch_infra: scrape_queue, player_discovery_batch, player_queue_ref\n\n"
        "Schemas and migrations will NOT be touched.",
        title="[red]Reset Database[/red]",
        border_style="red",
    ))

    if not yes:
        confirm = typer.confirm("Continue?", default=False)
        if not confirm:
            raise typer.Exit(code=0)

    asyncio.run(_do_reset(console))


async def _do_reset(console: object) -> None:
    import asyncpg  # type: ignore[import-untyped]

    from config.settings import Settings

    settings = Settings()  # type: ignore[call-arg]
    db = settings.db
    dsn = (
        f"postgresql://{db.user}:{db.password.get_secret_value()}"
        f"@{db.host}:{db.port}/{db.name}"
    )

    conn = await asyncpg.connect(dsn, timeout=5)
    try:
        tables = [
            ("sch_shared", "tbl_player_info"),
            ("sch_shared", "tbl_player_photo"),
            ("sch_shared", "tbl_player_positions"),
            ("sch_shared", "tbl_players"),
            ("sch_shared", "tbl_countries"),
            ("sch_shared", "tbl_confederations"),
            ("sch_shared", "tbl_gender"),
            ("sch_infra", "scrape_queue"),
            ("sch_infra", "player_discovery_batch"),
            ("sch_infra", "player_queue_ref"),
        ]
        for schema, table in tables:
            await conn.execute(
                f"TRUNCATE {schema}.{table} RESTART IDENTITY CASCADE"
            )
            msg = f"  [bold green]OK  [/bold green] {schema}.{table} truncated"
            console.print(msg)  # type: ignore[attr-defined]
        await conn.execute(
            "INSERT INTO sch_shared.tbl_gender (gender) VALUES ('M'), ('F')"
        )
        console.print(  # type: ignore[attr-defined]
            "  [bold green]OK  [/bold green] sch_shared.tbl_gender re-seeded"
        )
    finally:
        await conn.close()

    console.print(  # type: ignore[attr-defined]
        "\n[green]Reset complete. Ready to scrape from scratch.[/green]"
    )


def main() -> None:
    """Run the CLI."""
    app()
