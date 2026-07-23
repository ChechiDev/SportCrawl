"""Players CLI sub-app for sportcrawl."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import asyncpg  # type: ignore[import-untyped]
import typer
from rich.console import Console

from cli.header import print_header
from config.settings import Settings
from core.preflight import run_checks
from core.preflight.checks import check_stale_queue
from core.preflight.result import CheckResult

players_app = typer.Typer(name="players", help="Scrape players pipeline")
console = Console()

_MAX_SEED_RETRIES = 5
_SEED_RETRY_WAIT = 60


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
    async with PydollEngine(
        profile_dir=f"{settings.scraping.chrome_profile_dir}-seed-countries"
    ) as engine:
        scraper = CountryScraper(engine, settings.scraping, session_factory)
        await scraper.scrape(_COUNTRIES_URL)


async def _seed_country_squads(settings: Settings) -> None:
    import logging

    logging.getLogger("pydoll").setLevel(logging.WARNING)
    logging.getLogger("infrastructure").setLevel(logging.WARNING)
    logging.getLogger("ports.scraper").setLevel(logging.ERROR)

    from infrastructure.browser.pydoll_engine import PydollEngine
    from infrastructure.persistence.session import create_session_factory
    from infrastructure.scraping.country_squads import CountrySquadsScraper

    _SQUADS_URL = "https://fbref.com/en/squads/"
    session_factory = create_session_factory(settings.db)
    async with PydollEngine(
        profile_dir=f"{settings.scraping.chrome_profile_dir}-seed-squads"
    ) as engine:
        scraper = CountrySquadsScraper(engine, settings.scraping, session_factory)
        await scraper.scrape(_SQUADS_URL)


async def _seed_with_retry(
    seed_fn: Callable[[], Awaitable[None]],
    count_sql: str,
    label: str,
    dsn: str,
) -> int:
    """Run *seed_fn* with retry logic and return the final row count.

    Args:
        seed_fn: Async callable that performs the seed scrape.
        count_sql: SQL query that returns the count of seeded rows.
        label: Human-readable label for progress messages.
        dsn: asyncpg DSN for the count query.

    Returns:
        Number of rows present after seeding.

    Raises:
        typer.Exit: if all retries are exhausted.
    """
    from core.exceptions.scraper import ScraperError

    for _attempt in range(1, _MAX_SEED_RETRIES + 1):
        console.print(
            f"  [dim]→[/dim]  [dim]Seeding {label}...[/dim]{' ' * 20}",
            end="\r",
        )
        try:
            await seed_fn()
            break
        except ScraperError:
            if _attempt >= _MAX_SEED_RETRIES:
                console.print(
                    f"  [red]✗[/red]  {label.capitalize()} scrape failed"
                    f" after {_MAX_SEED_RETRIES} retries.{' ' * 20}"
                )
                raise typer.Exit(code=1)
            console.print(
                f"  [yellow]⚠[/yellow]  Rate limited — retrying in {_SEED_RETRY_WAIT}s"
                f" ({_attempt}/{_MAX_SEED_RETRIES}){' ' * 20}",
                end="\r",
            )
            await asyncio.sleep(_SEED_RETRY_WAIT)

    conn = await asyncpg.connect(dsn, timeout=5)
    try:
        count = await conn.fetchval(count_sql)
    finally:
        await conn.close()
    return count  # type: ignore[no-any-return]


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

    if not skip_preflight:
        console.print("[bold white]Checking requirements...[/bold white]")
        results = await run_checks(dsn, "club_teams", console, compact=False)

        seed_failed = next(
            (r for r in results if r.name == "Seed data" and not r.passed), None
        )
        if seed_failed and "countries" in seed_failed.detail:
            country_count = await _seed_with_retry(
                lambda: _seed_countries(settings),
                "SELECT count(*) FROM sch_shared.tbl_countries",
                "countries",
                dsn,
            )
            console.print(
                f"  [cyan]✓[/cyan]  {country_count} countries loaded.{' ' * 40}"
            )
            # Mark only the seed check as resolved
            results = [
                CheckResult(name=r.name, passed=True, detail=r.detail, fatal=r.fatal)
                if r.name == "Seed data" and not r.passed
                else r
                for r in results
            ]
        squads_failed = next(
            (r for r in results if r.name == "Country squads" and not r.passed), None
        )
        if squads_failed:
            squads_count = await _seed_with_retry(
                lambda: _seed_country_squads(settings),
                "SELECT count(*) FROM sch_shared.tbl_country_squads",
                "country squads",
                dsn,
            )
            console.print(
                f"  [cyan]✓[/cyan]  {squads_count} country squads loaded.{' ' * 40}"
            )
            results = [
                CheckResult(name=r.name, passed=True, detail=r.detail, fatal=r.fatal)
                if r.name == "Country squads" and not r.passed
                else r
                for r in results
            ]
        if seed_failed or squads_failed:
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

    if not all_countries and not country:
        console.print("[red]Specify --country or --all.[/red]")
        raise typer.Exit(code=1)

    from rich.rule import Rule

    from scripts.scrape_pipeline import main as pipeline_main

    console.print()
    console.print(Rule(style="blue dim"))
    console.print()
    if with_player_info and all_countries:
        await pipeline_main(workers=workers, all_countries=True, with_teams=True)
    else:
        await pipeline_main(
            workers=workers,
            all_countries=all_countries,
            with_teams=True,
        )
