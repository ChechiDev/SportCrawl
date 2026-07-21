"""Players CLI sub-app for sportcrawl."""
from __future__ import annotations

import asyncio

import asyncpg  # type: ignore[import-untyped]
import typer
from rich.console import Console

from cli.header import print_header
from config.settings import Settings
from core.preflight import run_checks
from core.preflight.checks import check_stale_queue
from core.preflight.result import CheckResult
from scripts.scrape_players import main_all, main_countries

players_app = typer.Typer(name="players", help="Scrape players pipeline")
console = Console()


async def _seed_countries(settings: Settings) -> None:
    import logging
    logging.getLogger("pydoll").setLevel(logging.WARNING)
    logging.getLogger("infrastructure").setLevel(logging.WARNING)
    logging.getLogger("ports.scraper").setLevel(logging.ERROR)

    from infrastructure.browser.pydoll_engine import PydollEngine
    from infrastructure.persistence.session import create_session_factory
    from infrastructure.scraping.countries import CountryScraper

    _COUNTRIES_URL = "https://fbref.com/en/countries/"
    session_factory = create_session_factory(settings.db)
    async with PydollEngine() as engine:
        scraper = CountryScraper(engine, settings.scraping, session_factory)
        await scraper.scrape(_COUNTRIES_URL)


def _build_dsn(settings: Settings) -> str:
    db = settings.db
    return (
        f"postgresql://{db.user}:{db.password.get_secret_value()}"
        f"@{db.host}:{db.port}/{db.name}"
    )


@players_app.command("start")
def players_start(
    country: str | None = typer.Option(
        None, "--country", "-c", help="Comma-separated codes, e.g. ESP,ARG"
    ),
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
    country: str | None,
    all_countries: bool,
    with_player_info: bool,
    workers: int,
    recover_stale: bool,
    skip_preflight: bool,
) -> None:
    settings = Settings()  # type: ignore[call-arg]
    dsn = _build_dsn(settings)
    seed_failed = None

    print_header(console)

    from core.preflight.renderer import render_summary

    if not skip_preflight:
        console.print("[bold white]Checking requirements...[/bold white]")
        results = await run_checks(dsn, "players", console, compact=False)

        seed_failed = next(
            (r for r in results if r.name == "Seed data" and not r.passed), None
        )
        if seed_failed and "countries" in seed_failed.detail:
            from core.exceptions.scraper import ScraperError
            _MAX_SEED_RETRIES = 5
            _SEED_RETRY_WAIT = 60
            for _attempt in range(1, _MAX_SEED_RETRIES + 1):
                console.print(f"  [dim]→[/dim]  [dim]Seeding countries (attempt {_attempt}/{_MAX_SEED_RETRIES})...[/dim]{' ' * 20}", end="\r")
                try:
                    await _seed_countries(settings)
                    break
                except ScraperError:
                    if _attempt >= _MAX_SEED_RETRIES:
                        console.print(f"  [red]✗[/red]  Countries scrape failed after {_MAX_SEED_RETRIES} retries.{' ' * 20}")
                        raise typer.Exit(code=1)
                    console.print(f"  [yellow]⚠[/yellow]  Rate limited — retrying in {_SEED_RETRY_WAIT}s ({_attempt}/{_MAX_SEED_RETRIES}){' ' * 20}")
                    await asyncio.sleep(_SEED_RETRY_WAIT)
            conn = await asyncpg.connect(dsn, timeout=5)
            try:
                country_count = await conn.fetchval(
                    "SELECT count(*) FROM sch_shared.tbl_countries"
                )
            finally:
                await conn.close()
            console.print(f"  [cyan]✓[/cyan]  {country_count} countries loaded.{' ' * 40}")
            # Mark seed check as resolved and run stale queue check
            results = [
                CheckResult(name=r.name, passed=True, detail=r.detail, fatal=r.fatal)
                if not r.passed else r
                for r in results
            ]
            stale_result = await check_stale_queue(dsn)
            if not stale_result.passed:
                from core.preflight.renderer import render_check
                render_check(stale_result, console)
            results.append(stale_result)

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
            )
            result = await conn.execute(_sql)
            updated = int(result.split()[-1])
            console.print(f"  Reset {updated} stale jobs.")
        finally:
            await conn.close()

    import logging
    logging.getLogger("pydoll").setLevel(logging.WARNING)
    logging.getLogger("infrastructure").setLevel(logging.WARNING)
    logging.getLogger("ports.scraper").setLevel(logging.ERROR)

    step = 2 if not skip_preflight and seed_failed else 1
    if with_player_info and all_countries:
        from scripts.scrape_pipeline import main as pipeline_main

        console.print()
        await pipeline_main(workers=workers, all_countries=True)
        return

    console.print()
    console.print("[bold]Scraping Players[/bold]")
    if all_countries:
        await main_all(workers=workers)
    elif country:
        codes = [c.strip().upper() for c in country.split(",") if c.strip()]
        await main_countries(codes, workers=workers)
    else:
        console.print("[red]Specify --country or --all.[/red]")
        raise typer.Exit(code=1)

    if with_player_info:
        console.print()
        console.print("[bold]Scraping Single Player Stats[/bold]")
        from scripts.scrape_player_info import main as scrape_info

        await scrape_info(workers=workers, seed=True)
