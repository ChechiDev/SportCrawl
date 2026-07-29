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


async def _seed_country_players_urls(settings: Settings) -> None:
    import logging

    logging.getLogger("pydoll").setLevel(logging.WARNING)
    logging.getLogger("infrastructure").setLevel(logging.WARNING)
    logging.getLogger("ports.scraper").setLevel(logging.ERROR)

    from infrastructure.browser.pydoll_engine import PydollEngine
    from infrastructure.persistence.session import create_session_factory
    from infrastructure.scraping.country_players import CountryPlayersScraper

    _PLAYERS_INDEX_URL = "https://fbref.com/en/players/country/"
    session_factory = create_session_factory(settings.db)
    async with PydollEngine(
        profile_dir=f"{settings.scraping.chrome_profile_dir}-seed-players-urls"
    ) as engine:
        scraper = CountryPlayersScraper(engine, settings.scraping, session_factory)
        await scraper.scrape(_PLAYERS_INDEX_URL)


async def _sync_backend_urls() -> None:
    from scripts.backfill_backend_urls import sync_preflight

    await sync_preflight()


async def _seed_competitions(settings: Settings) -> int:
    import logging

    logging.getLogger("pydoll").setLevel(logging.WARNING)
    logging.getLogger("infrastructure").setLevel(logging.WARNING)
    logging.getLogger("ports.scraper").setLevel(logging.ERROR)

    from infrastructure.browser.pydoll_engine import PydollEngine
    from infrastructure.persistence.session import create_session_factory
    from infrastructure.scraping.competitions import CompetitionsScraper

    _COMPS_URL = "https://fbref.com/en/comps/"
    session_factory = create_session_factory(settings.db)
    async with PydollEngine(
        profile_dir=f"{settings.scraping.chrome_profile_dir}-seed-competitions"
    ) as engine:
        scraper = CompetitionsScraper(engine, settings.scraping, session_factory)
        page = await scraper.scrape(_COMPS_URL)
        return len(page.competitions)


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
            f"  [bold cyan]→[/bold cyan]  [dim]Seeding {label}...[/dim]{' ' * 20}",
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
            for remaining in range(_SEED_RETRY_WAIT, 0, -1):
                console.print(
                    f"  [bold cyan]![/bold cyan]  Rate limited — Retrying in"
                    f" {remaining}s ({_attempt}/{_MAX_SEED_RETRIES}){' ' * 20}",
                    end="\r",
                )
                await asyncio.sleep(1)

    conn = await asyncpg.connect(dsn, timeout=5)
    try:
        count = await conn.fetchval(count_sql)
    finally:
        await conn.close()
    return count  # type: ignore[no-any-return]


async def _fetchval(dsn: str, sql: str) -> int:
    conn = await asyncpg.connect(dsn, timeout=5)
    try:
        return await conn.fetchval(sql)  # type: ignore[no-any-return]
    finally:
        await conn.close()


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

    print_header(console)

    if not skip_preflight:
        console.print("[bold white]Checking requirements...[/bold white]")

        results = await run_checks(
            dsn, "club_teams", console, compact=False, with_seed_checks=False
        )

        existing_countries = await _fetchval(
            dsn, "SELECT count(*) FROM sch_fbref_shared.tbl_countries"
        )

        if existing_countries:
            msg = f"  [cyan]✓[/cyan]  {existing_countries} Countries"
            console.print(msg + " loaded successfully.")
        else:
            country_count = await _seed_with_retry(
                lambda: _seed_countries(settings),
                "SELECT count(*) FROM sch_fbref_shared.tbl_countries",
                "countries",
                dsn,
            )
            msg = f"  [cyan]✓[/cyan]  {country_count} Countries"
            console.print(msg + " loaded successfully.")

        existing_squads = await _fetchval(
            dsn, "SELECT count(*) FROM sch_fbref_shared.tbl_country_squads"
        )

        if existing_squads:
            msg = f"  [cyan]✓[/cyan]  {existing_squads} Country Teams"
            console.print(msg + " loaded successfully.")
        else:
            squads_count = await _seed_with_retry(
                lambda: _seed_country_squads(settings),
                "SELECT count(*) FROM sch_fbref_shared.tbl_country_squads",
                "country squads",
                dsn,
            )
            msg = f"  [cyan]✓[/cyan]  {squads_count} Country Teams"
            console.print(msg + " loaded successfully.")

        missing_players_url = await _fetchval(
            dsn,
            (
                "SELECT count(*) FROM sch_fbref_shared.tbl_countries"
                " WHERE players_url IS NULL"
            ),
        )

        if missing_players_url:
            players_url_count = await _seed_with_retry(
                lambda: _seed_country_players_urls(settings),
                (
                    "SELECT count(*) FROM sch_fbref_shared.tbl_countries "
                    "WHERE players_url IS NOT NULL"
                ),
                "country players URLs",
                dsn,
            )
            msg = (
                f"  [cyan]✓[/cyan]  {players_url_count} Countries "
                "with Players loaded successfully."
            )
            console.print(msg)
        else:
            console.print(
                "  [cyan]✓[/cyan]  All Countries with Players loaded successfully."
            )

        existing_comps = await _fetchval(
            dsn, "SELECT count(*) FROM sch_fbref_shared.tbl_competition"
        )
        if existing_comps:
            console.print(
                f"  [cyan]✓[/cyan]  {existing_comps} Competitions loaded successfully."
            )
        else:
            async def _scrape_competitions() -> None:
                await _seed_competitions(settings)

            comp_count = await _seed_with_retry(
                _scrape_competitions,
                "SELECT count(*) FROM sch_fbref_shared.tbl_competition",
                "competitions",
                dsn,
            )
            console.print(
                f"  [cyan]✓[/cyan]  {comp_count} Competitions loaded successfully."
            )

        await _sync_backend_urls()

        fatal_failures = [r for r in results if not r.passed and r.fatal]
        if fatal_failures:
            raise typer.Exit(code=1)

    if recover_stale:
        conn = await asyncpg.connect(dsn, timeout=5)
        try:
            _sql = (
                "UPDATE sch_fbref_infra.scrape_queue"
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
    country_list = [c.strip().upper() for c in country.split(",")] if country else None
    if all_countries and country_list:
        console.print(
            "[yellow]Warning:[/] --all and --country are mutually exclusive. "
            "--all takes precedence."
        )
    if with_player_info and all_countries:
        await pipeline_main(
            workers=workers,
            all_countries=True,
            country=country_list,
            with_teams=True,
        )
    else:
        await pipeline_main(
            workers=workers,
            all_countries=all_countries,
            country=country_list,
            with_teams=True,
        )
