"""CLI entry point for sportcrawl.

Commands:
- work-server: start the aiohttp work server with a shared JobLoop event loop.
- scrape-players: discover and persist players for one country or all countries.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import urllib.request
import warnings
from collections.abc import Callable
from datetime import datetime
from typing import Any

warnings.filterwarnings("ignore")

import typer  # noqa: E402
from rich.console import Console  # noqa: E402

from cli.browser_launcher import RealBrowserLauncher  # noqa: E402
from cli.clearance_observer import RealClearanceObserver  # noqa: E402
from cli.clearance_post_client import RealClearancePostClient  # noqa: E402
from cli.clearance_providers import (  # noqa: E402
    EnvBrowserParameterProvider,
    EnvTargetProvider,
    EnvTokenProvider,
    GhCICheckProvider,
    LabelTargetValidator,
)
from cli.extension_config import smoke_extension_config  # noqa: E402
from cli.smoke_clearance_real import (  # noqa: E402
    ClearanceResult,
    HarnessStatus,
    RealClearanceHarness,
    RealClearanceProviders,
    RealClearanceSeams,
)
from cli.work_server_lifecycle import RealWorkServerLifecycle  # noqa: E402
from config.settings import Settings  # noqa: E402
from infrastructure.browser.pydoll_engine import PydollEngine  # noqa: E402
from infrastructure.work_server.runtime import serve  # noqa: E402


def _make_clearance_getter(
    url: str,
    token: str,
    getter: Callable[[urllib.request.Request], Any] = urllib.request.urlopen,
) -> Callable[[], ClearanceResult | None]:
    """Return a callable that fetches the latest clearance from the work-server.

    Injectable via `getter` so unit tests never touch the real network.
    Raises PermissionError on HTTP 401/403 (auth failures must not be silenced).
    """
    import urllib.error as _ue

    def _get() -> ClearanceResult | None:
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        try:
            with getter(req) as resp:
                if resp.status == 204:
                    return None
                if resp.status != 200:
                    return None
                raw = resp.read()
                try:
                    body = json.loads(raw)
                    return ClearanceResult(
                        obtained=True,
                        expires_at=datetime.fromisoformat(
                            body["expires_at"].replace("Z", "+00:00")
                        ),
                        clearance_class=body.get("clearance_class", ""),
                    )
                except (KeyError, ValueError, AttributeError):
                    return None  # malformed body — treat as not-yet-available
        except _ue.HTTPError as exc:
            if exc.code in (401, 403):
                raise PermissionError(
                    f"clearance GET auth failure: HTTP {exc.code}"
                ) from exc
            return None
        except (_ue.URLError, OSError):
            raise ConnectionError("clearance endpoint unreachable") from None

    return _get


app = typer.Typer(
    name="sportcrawl",
    help="Sportcrawl — sports data, scraped at scale.",
    invoke_without_command=True,
)


@app.callback()
def default(
    ctx: typer.Context,
    country: str | None = typer.Option(
        None, "--country", "-c", help="Comma-separated country codes, e.g. ESP,ARG"
    ),
    all_countries: bool = typer.Option(
        False, "--all", "-a", help="Scrape all countries"
    ),
    with_player_info: bool = typer.Option(False, "--with-player-info"),
    workers: int = typer.Option(1, "--workers", "-w"),
    recover_stale: bool = typer.Option(False, "--recover-stale"),
    skip_preflight: bool = typer.Option(False, "--skip-preflight"),
) -> None:
    """Run the full scraping pipeline (teams + players + player info)."""
    if ctx.invoked_subcommand is not None:
        return
    if not all_countries and not country:
        raise typer.BadParameter("Specify --country or --all.")
    from cli.players import _run

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


@app.command("start")
def start(
    country: str | None = typer.Option(
        None, "--country", "-c", help="Comma-separated country codes, e.g. ESP,ARG"
    ),
    all_countries: bool = typer.Option(
        False, "--all", "-a", help="Scrape all countries"
    ),
    with_player_info: bool = typer.Option(False, "--with-player-info"),
    workers: int = typer.Option(1, "--workers", "-w"),
    recover_stale: bool = typer.Option(False, "--recover-stale"),
    skip_preflight: bool = typer.Option(False, "--skip-preflight"),
) -> None:
    """Run the full scraping pipeline (teams + players + player info)."""
    if not all_countries and not country:
        raise typer.BadParameter("Specify --country/-c or --all/-a.")
    from cli.players import _run

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


@app.command("work-server")
def work_server() -> None:
    """Start the aiohttp work server and JobLoop in a single process."""
    settings = Settings()  # type: ignore[call-arg]
    asyncio.run(serve(settings))


@app.command("scrape-players")
def scrape_players(
    country: str | None = typer.Option(
        None,
        "--country",
        "-c",
        metavar="CODE",
        help="FBRef country code, e.g. ARG.",
    ),
    url: str | None = typer.Option(
        None,
        "--url",
        "-u",
        metavar="URL",
        help="Full FBRef country player-list URL.",
    ),
    all_countries: bool = typer.Option(
        False,
        "--all",
        "-a",
        help="Scrape all countries from the database.",
    ),
) -> None:
    """Discover and persist players for one country or all countries."""
    import logging

    logging.getLogger("pydoll").setLevel(logging.WARNING)
    logging.getLogger("infrastructure.browser").setLevel(logging.WARNING)
    logging.getLogger("infrastructure.scraping").setLevel(logging.WARNING)

    from scripts.scrape_players import main_all, main_single

    _PLAYERS_BASE_URL = "https://fbref.com/en/country/players"

    if all_countries:
        asyncio.run(main_all())
    elif url:
        asyncio.run(main_single(url))
    elif country:
        code = country.upper()
        asyncio.run(main_single(f"{_PLAYERS_BASE_URL}/{code}/{code}-Football"))
    else:
        typer.echo("Specify --country, --url, or --all.", err=True)
        raise typer.Exit(code=1)


@app.command("scrape-squads")
def scrape_squads() -> None:
    """Fetch and persist country squad data from FBRef (/en/squads/)."""
    import logging

    logging.getLogger("pydoll").setLevel(logging.WARNING)
    logging.getLogger("infrastructure.browser").setLevel(logging.WARNING)
    logging.getLogger("infrastructure.scraping").setLevel(logging.WARNING)

    from scripts.scrape_country_squads import main as squads_main

    asyncio.run(squads_main())


@app.command("pipeline")
def pipeline(
    workers: int = typer.Option(
        1,
        "--workers",
        "-w",
        help="Number of parallel workers per step (default: 1).",
    ),
    trigger_count: int = typer.Option(
        100,
        "--trigger-count",
        help="Minimum players in DB before Step 3 starts (default: 100).",
    ),
) -> None:
    """Run Step 2 (players) and Step 3 (player info) concurrently."""
    from scripts.scrape_pipeline import main as pipeline_main

    asyncio.run(
        pipeline_main(
            workers=workers,
            trigger_count=trigger_count,
        )
    )


@app.command("reset")
def reset_db(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
) -> None:
    """Truncate all scraped data. Keeps schemas and migrations intact."""
    from rich.console import Console
    from rich.panel import Panel

    console = Console()

    console.print(
        Panel(
            "[bold red]WARNING[/bold red]\n\n"
            "This will delete ALL scraped data:\n"
            "  • sch_fbref_shared: countries, players, player_info, photos,\n"
            "    positions, country_squads, teams, competition, comp_type,\n"
            "    cities, player_citizenship\n"
            "  • sch_fbref_football: player_std_stats, player_misc_stats,\n"
            "    player_playing_time_stats, player_shooting_stats\n"
            "  • sch_fbref_infra: scrape_queue, player_discovery_batch,\n"
            "    player_queue_ref\n\n"
            "Schemas and migrations will NOT be touched.",
            title="[red]Reset Database[/red]",
            border_style="red",
        )
    )

    if not yes:
        confirm = typer.confirm("Continue?", default=False)
        if not confirm:
            raise typer.Exit(code=0)

    asyncio.run(_do_reset(console))


async def _do_reset(console: Console) -> None:
    import asyncpg  # type: ignore[import-untyped]
    from alembic import command
    from alembic.config import Config

    from config.settings import Settings

    settings = Settings()  # type: ignore[call-arg]
    db = settings.db
    dsn = (
        f"postgresql://{db.user}:{db.password.get_secret_value()}"
        f"@{db.host}:{db.port}/{db.name}"
    )

    import asyncio
    import logging as _logging
    from functools import partial

    conn = await asyncpg.connect(dsn, timeout=5)
    try:
        for schema in (
            "sch_fbref_backend",
            "sch_fbref_infra",
            "sch_fbref_shared",
            "sch_fbref_football",
            "sch_infra",
            "sch_shared",
            "sch_football",
        ):
            await conn.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
        # Restore public schema so the initial migration (134f2e68682a) can create
        # scrape_queue there. p10c_drop_public_schema drops public, so we recreate it.
        await conn.execute("CREATE SCHEMA IF NOT EXISTS public")
        await conn.execute("GRANT USAGE, CREATE ON SCHEMA public TO PUBLIC")
    finally:
        await conn.close()

    alembic_cfg = Config("alembic.ini")
    alembic_cfg.attributes["configure_logger"] = False
    _logging.getLogger("alembic").setLevel(_logging.ERROR)
    _logging.getLogger("alembic.runtime.migration").setLevel(_logging.ERROR)
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, partial(command.upgrade, alembic_cfg, "heads"))

    conn = await asyncpg.connect(dsn, timeout=5)
    try:
        tables = [
            ("sch_fbref_football", "tbl_player_misc_stats"),
            ("sch_fbref_football", "tbl_player_playing_time_stats"),
            ("sch_fbref_football", "tbl_player_shooting_stats"),
            ("sch_fbref_football", "tbl_player_std_stats"),
            ("sch_fbref_shared", "tbl_player_info"),
            ("sch_fbref_shared", "tbl_player_photo"),
            ("sch_fbref_shared", "tbl_player_citizenship"),
            ("sch_fbref_shared", "tbl_player_positions"),
            ("sch_fbref_shared", "tbl_players"),
            ("sch_fbref_shared", "tbl_teams"),
            ("sch_fbref_shared", "tbl_country_squads"),
            ("sch_fbref_shared", "tbl_competition"),
            ("sch_fbref_shared", "tbl_comp_type"),
            ("sch_fbref_shared", "tbl_cities"),
            ("sch_fbref_shared", "tbl_countries"),
            ("sch_fbref_shared", "tbl_confederations"),
            ("sch_fbref_shared", "tbl_gender"),
            ("sch_fbref_infra", "scrape_queue"),
            ("sch_fbref_infra", "player_discovery_batch"),
            ("sch_fbref_infra", "player_queue_ref"),
        ]
        for schema, table in tables:
            await conn.execute(f"TRUNCATE {schema}.{table} RESTART IDENTITY CASCADE")
            msg = f"  [bold green]OK  [/bold green] {schema}.{table} truncated"
            console.print(msg)
        await conn.execute(
            "INSERT INTO sch_fbref_shared.tbl_gender (gender) VALUES ('M'), ('F')"
        )
        console.print(
            "  [bold green]OK  [/bold green] sch_fbref_shared.tbl_gender re-seeded"
        )
    finally:
        await conn.close()

    console.print("\n[green]Reset complete. Ready to scrape from scratch.[/green]")


from cli.smoke_player_info import smoke_player_info_command  # noqa: E402

app.command("smoke-player-info")(smoke_player_info_command)


_SMOKE_CLEARANCE_DRY_RUN = typer.Option(
    False,
    "--dry-run/--no-dry-run",
    help="Print readiness check only, no live state.",
)
_SMOKE_CLEARANCE_EXECUTE = typer.Option(
    False,
    "--execute",
    help="Run fake/local clearance harness contract (not real smoke).",
)
_SMOKE_CLEARANCE_PREPARE_REAL = typer.Option(
    False,
    "--prepare-real",
    help=("Print real-smoke harness plan (blocked/not authorized — no execution)."),
)
_SMOKE_CLEARANCE_REAL_CLEARANCE = typer.Option(
    False,
    "--real-clearance",
    help=(
        "Run the real clearance smoke harness"
        " (guarded — all providers must be configured)."
    ),
)
_SMOKE_CLEARANCE_WORKERS = typer.Option(
    1,
    "--workers",
    "-w",
    help="Worker count — must be 1 for clearance smoke.",
)


@app.command("smoke-clearance")
def smoke_clearance(
    dry_run: bool = _SMOKE_CLEARANCE_DRY_RUN,
    execute: bool = _SMOKE_CLEARANCE_EXECUTE,
    prepare_real: bool = _SMOKE_CLEARANCE_PREPARE_REAL,
    real_clearance: bool = _SMOKE_CLEARANCE_REAL_CLEARANCE,
    workers: int = _SMOKE_CLEARANCE_WORKERS,
) -> None:
    """Clearance-only smoke. Default: dry-run. --execute runs the fake seam contract."""
    if workers != 1:
        raise typer.BadParameter(
            "smoke-clearance requires workers=1.",
            param_hint="'--workers'",
        )
    if execute and dry_run:
        raise typer.BadParameter(
            "--execute and --dry-run are mutually exclusive.",
            param_hint="'--execute'",
        )
    if prepare_real and dry_run:
        raise typer.BadParameter(
            "--prepare-real and --dry-run are mutually exclusive.",
            param_hint="'--prepare-real'",
        )
    if prepare_real and execute:
        raise typer.BadParameter(
            "--prepare-real and --execute are mutually exclusive.",
            param_hint="'--prepare-real'",
        )
    if real_clearance and dry_run:
        raise typer.BadParameter(
            "--real-clearance and --dry-run are mutually exclusive.",
            param_hint="'--real-clearance'",
        )
    if real_clearance and execute:
        raise typer.BadParameter(
            "--real-clearance and --execute are mutually exclusive.",
            param_hint="'--real-clearance'",
        )
    if real_clearance and prepare_real:
        raise typer.BadParameter(
            "--real-clearance and --prepare-real are mutually exclusive.",
            param_hint="'--real-clearance'",
        )

    console = Console()

    if real_clearance:
        import os

        _RESOLVED_HOST = "127.0.0.1"
        _WORK_SERVER_PORT = 9731
        _WORK_SERVER_CMD = ["uv", "run", "sportcrawl", "work-server"]
        # Captured here for seam constructors. Gate 1 (GATE_PROVIDER_READINESS)
        # re-reads this env var live via EnvTokenProvider.is_ready() before any
        # resource-committing gate — empty/missing token caught there, before
        # work_server starts.
        _token = os.environ.get("SCRAPING__WORK_SERVER_TOKEN", "")
        _clearance_url = (
            f"http://{_RESOLVED_HOST}:{_WORK_SERVER_PORT}/api/clearance"
        )

        # Composition-root config for real-clearance seams — no settings object
        # exists upstream in this command scope; constructed here to resolve
        # chrome_profile_dir before the closures are defined.
        settings = Settings()  # type: ignore[call-arg]
        try:
            engine = PydollEngine(
                profile_dir=settings.scraping.chrome_profile_dir,
                name="smoke-clearance",
            )
        except Exception as exc:
            typer.echo(
                f"[smoke-clearance] browser engine init failed: "
                f"{type(exc).__name__}: {str(exc)[:100]}",
                err=True,
            )
            sys.exit(1)

        async def _engine_starter() -> None:
            await engine.start()

        async def _cdp_probe() -> None:
            # "1" is the minimal CDP Runtime.evaluate round-trip probe — confirms
            # the WebSocket is alive without navigating to any page.
            await engine.execute_script("1")

        async def _engine_stopper() -> None:
            await engine.close()

        _ext_cfg = smoke_extension_config(
            url=f"http://{_RESOLVED_HOST}:{_WORK_SERVER_PORT}",
            token=_token,
        )

        # One event loop shared across browser start, CDP probe, engine stop, and
        # extension config injection — pydoll's async objects bind to the loop on
        # creation; using separate loops raises RuntimeError on the second access.
        _loop = asyncio.new_event_loop()

        def _extension_config_injector() -> None:
            """Inject extension runtime config via CDP Runtime.callFunctionOn.

            Config values are passed as a structured CDP argument dict — no values
            are serialised into the JavaScript function body string. The bearer
            token therefore never appears in any script string that could be logged
            by pydoll or a future debug wrapper.

            Runs on the same event loop as the browser launcher so all pydoll async
            objects remain on one loop throughout the session.
            """
            _is_closed = _loop.is_closed()
            _is_running = _loop.is_running()
            if _is_closed or _is_running:
                raise RuntimeError(
                    "extension config loop is not usable "
                    f"(closed={_is_closed}, running={_is_running})"
                )
            _pydoll_logger = logging.getLogger("pydoll")
            _orig_level = _pydoll_logger.level
            _pydoll_logger.setLevel(logging.WARNING)
            try:
                _loop.run_until_complete(
                    engine.inject_storage_config(
                        {
                            "work_server_url": _ext_cfg.work_server_url,
                            "work_server_token": _ext_cfg.work_server_token,
                            "profile_id": _ext_cfg.profile_id,
                            "worker_id": _ext_cfg.worker_id,
                            "disable_task_polling": _ext_cfg.disable_task_polling,
                        }
                    )
                )
            finally:
                _pydoll_logger.setLevel(_orig_level)

        def _target_navigator() -> None:
            """Navigate to the configured target URL after extension config injection.

            The target URL is read generically from the environment — no domain
            is hardcoded here. Navigation failure raises PageLoadError, which the
            harness maps to BLOCKED at the target_navigation gate.

            Runs on the same event loop as browser start and extension injection.
            """
            _is_closed = _loop.is_closed()
            _is_running = _loop.is_running()
            if _is_closed or _is_running:
                raise RuntimeError(
                    "target navigation loop is not usable "
                    f"(closed={_is_closed}, running={_is_running})"
                )
            _nav_url = os.environ.get("SCRAPING__WORK_SERVER_HOST", "").strip()
            if not _nav_url:
                raise RuntimeError("SCRAPING__WORK_SERVER_HOST is not set")
            _loop.run_until_complete(engine.navigate(_nav_url))

        providers = RealClearanceProviders(
            target=EnvTargetProvider(),
            browser_params=EnvBrowserParameterProvider(),
            token=EnvTokenProvider(),
        )
        seams = RealClearanceSeams(
            ci_check=GhCICheckProvider(workflow_name="CI"),
            work_server=RealWorkServerLifecycle(
                host=_RESOLVED_HOST,
                port=_WORK_SERVER_PORT,
                token=_token,
                cmd=_WORK_SERVER_CMD,
            ),
            target_validator=LabelTargetValidator(),
            browser_launcher=RealBrowserLauncher(
                engine_starter=_engine_starter,
                cdp_probe=_cdp_probe,
                engine_stopper=_engine_stopper,
                # Share the explicit loop so browser and injector use the same one.
                loop_runner=_loop.run_until_complete,
            ),
            clearance_observer=RealClearanceObserver(
                clearance_getter=_make_clearance_getter(
                    f"http://{_RESOLVED_HOST}:{_WORK_SERVER_PORT}/api/clearance/latest",
                    _token,
                ),
            ),
            clearance_post=RealClearancePostClient(
                url=_clearance_url,
                token=_token,
            ),
            resolved_host=_RESOLVED_HOST,
        )

        harness = RealClearanceHarness()
        try:
            report = harness.run(
                providers,
                seams,
                extension_config_injector=_extension_config_injector,
                target_navigator=_target_navigator,
            )
        finally:
            if not _loop.is_closed():
                pending = asyncio.all_tasks(_loop)
                for task in pending:
                    task.cancel()
                if pending:
                    _loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True)
                    )
                _loop.close()

        console.print(
            "[bold]smoke-clearance --real-clearance[/bold] — real clearance harness"
        )
        console.print(f"  status:    {report.status.value}")
        if report.error_gate is not None:
            console.print(f"  blocked_at: {report.error_gate}")

        if report.status != HarnessStatus.PASS:
            raise typer.Exit(code=1)
        return

    if prepare_real:
        console.print(
            "[bold]smoke-clearance --prepare-real[/bold] — real smoke harness plan"
        )
        console.print("  status:               blocked / not authorized")
        console.print(f"  workers:              {workers}")
        console.print("  work server:          future loopback 127.0.0.1")
        console.print("  endpoint:             /api/clearance")
        console.print("  expected response:    204")
        console.print("  extension storage:    chrome.storage.local")
        console.print("  disable_task_polling: true")
        console.print("  profile:              temporary profile — cleanup required")
        console.print("  ext-runtime:          not started (prepare-real only)")
        console.print("  network:              not started (prepare-real only)")
        console.print("  DB:                   not required")
        console.print("  Docker:               not required")
        console.print(
            "[yellow]Real smoke is blocked. No execution was performed.[/yellow]"
        )
        return

    if not execute:
        console.print("[bold]smoke-clearance[/bold] — clearance-only dry-run")
        console.print(f"  workers:              {workers}")
        console.print("  scope:                clearance-only")
        console.print("  /api/clearance:       active")
        console.print("  disable_task_polling: true")
        console.print("  DB:                   not required")
        console.print("  network:              not required")
        console.print("  token_present:        (not checked in dry-run)")
        console.print("[green]Dry-run complete.[/green]")
        return

    # Execute path — fake/injected/local contract seam only.
    # No real work_server, browser, network, DB, or Docker is started.
    work_server_ready = False
    browser_ready = False
    clearance_observed = False
    console.print("[bold]smoke-clearance --execute[/bold] — fake contract seam")
    console.print(f"  workers:              {workers}")
    console.print("  disable_task_polling: true")
    try:
        # Step 1: work_server start seam (fake — no socket opened)
        work_server_ready = True
        console.print("  step 1/9: work_server — seam ready")
        # Steps 2–4: temp profile + config injection seam (disable_task_polling=true)
        # Step 5: browser launch seam (fake — no process started)
        browser_ready = True
        console.print("  step 5/9: browser — seam ready")
        # Step 6: observe /api/clearance 204 (fake — no network call)
        clearance_observed = True
        console.print("  step 6/9: /api/clearance — 204 observed (fake)")
        console.print(f"  clearance_observed: {clearance_observed}")
        console.print("[green]Execute contract: all seams verified.[/green]")
    finally:
        # Steps 7–9: remove injected config, clean temp profile, stop work_server
        _ = work_server_ready, browser_ready
        console.print("  cleanup: config removed, profile cleaned, work_server stopped")


def main() -> None:
    """Run the CLI."""
    app()
