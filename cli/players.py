"""Players CLI sub-app for sportcrawl."""
from __future__ import annotations

import asyncio
from typing import Optional

import asyncpg
import typer
from rich.console import Console

from config.settings import Settings
from core.preflight import run_checks
from scripts.scrape_players import main_all, main_single

players_app = typer.Typer(name="players", help="Scrape players pipeline")
console = Console()


def _build_dsn(settings: Settings) -> str:
    db = settings.db
    return (
        f"postgresql://{db.user}:{db.password.get_secret_value()}"
        f"@{db.host}:{db.port}/{db.name}"
    )


@players_app.command("start")
def players_start(
    country: Optional[str] = typer.Option(None, "--country", "-c"),
    all_countries: bool = typer.Option(False, "--all", "-a"),
    with_player_info: bool = typer.Option(False, "--with-player-info"),
    workers: int = typer.Option(1, "--workers", "-w"),
    recover_stale: bool = typer.Option(False, "--recover-stale"),
    skip_preflight: bool = typer.Option(False, "--skip-preflight"),
) -> None:
    """Scrape players (and optionally player info) for one or all countries."""
    asyncio.run(
        _run(
            country=country,
            all_countries=all_countries,
            with_player_info=with_player_info,
            workers=workers,
            recover_stale=recover_stale,
            skip_preflight=skip_preflight,
        )
    )


async def _run(
    country: Optional[str],
    all_countries: bool,
    with_player_info: bool,
    workers: int,
    recover_stale: bool,
    skip_preflight: bool,
) -> None:
    settings = Settings()  # type: ignore[call-arg]
    dsn = _build_dsn(settings)
    phase = "player_info" if with_player_info else "players"

    if not skip_preflight:
        results = await run_checks(dsn, phase, console)
        from core.preflight.renderer import render_summary

        render_summary(results, console)
        fatal_failures = [r for r in results if not r.passed and r.fatal]
        if fatal_failures:
            raise typer.Exit(code=1)

    if recover_stale:
        conn = await asyncpg.connect(dsn, timeout=5)
        try:
            _sql = (
                "UPDATE sch_infra.scrape_queue"
                " SET status = 'PENDING', locked_at = NULL"
                " WHERE status = 'IN_PROGRESS'"
                " AND locked_at < NOW() - INTERVAL '1 hour'"
                " RETURNING COUNT(*)"
            )
            updated = await conn.fetchval(_sql)
            console.print(f"  Reset {updated} stale jobs.")
        finally:
            await conn.close()

    _FBREF_BASE = "https://fbref.com/en/country/players"

    console.print("\n[bold]Step 1 — Scraping players[/bold]")
    if all_countries:
        await main_all()
    elif country:
        code = country.upper()
        await main_single(f"{_FBREF_BASE}/{code}/{code}-Football")
    else:
        console.print("[red]Specify --country or --all.[/red]")
        raise typer.Exit(code=1)

    if with_player_info:
        conn = await asyncpg.connect(dsn, timeout=5)
        try:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM sch_shared.tbl_players"
            )
        finally:
            await conn.close()
        console.print(
            f"\nAbout to scrape player info for ~{count} players "
            f"({count} requests). Continue? [y/N] ",
            end="",
        )
        answer = input()
        if answer.lower() != "y":
            raise typer.Exit(code=0)
        from scripts.scrape_player_info import main as scrape_info

        await scrape_info(workers=workers, seed=True)
