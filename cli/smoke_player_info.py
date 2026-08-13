"""smoke-player-info — operator smoke test for the player_info buffering path."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import asyncpg  # type: ignore[import-untyped]

import typer
from rich.console import Console

_CONSOLE = Console()

DEFAULT_SMOKE_ENV = Path.home() / ".config/sportcrawl/smoke.env"
DEFAULT_CANDIDATE_ID = "d70ce98e"
_SEARCH_PATH = (
    "sch_fbref_infra,sch_fbref_shared,sch_fbref_backend,sch_fbref_football,public"
)


def smoke_player_info_command(
    buffered: bool = typer.Option(
        True,
        "--buffered/--no-buffered",
        help="Enable buffered dispatch mode.",
    ),
    warm_pool: bool = typer.Option(
        False,
        "--warm-pool/--no-warm-pool",
        help="Enable warm browser pool (requires --buffered).",
    ),
    workers: int = typer.Option(
        2, "--workers", "-w", min=1, max=25, help="Worker count."
    ),
    candidate: str = typer.Option(
        DEFAULT_CANDIDATE_ID,
        "--candidate",
        help="Player ID (smoke-only controlled candidate).",
    ),
    smoke_env: Path = typer.Option(
        DEFAULT_SMOKE_ENV,
        "--smoke-env",
        help="Path to smoke.env file with POSTGRES_* credentials.",
    ),
    reset: bool = typer.Option(
        True,
        "--reset/--no-reset",
        help="Reset candidate to C3-equivalent before run.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Print config summary without connecting to DB or running scraper.",
    ),
) -> None:
    """Run a smoke test for player_info buffering against the isolated smoke DB.

    Targets 127.0.0.1:15432 only. Loads credentials from smoke.env.
    Never connects to production DB.
    """
    vals = _load_smoke_env(smoke_env)
    if vals is None:
        raise typer.Exit(code=1)

    if dry_run:
        _print_dry_run_summary(
            buffered, warm_pool, workers, candidate, smoke_env, reset, vals
        )
        return

    _apply_env(vals, buffered, warm_pool)
    asyncio.run(_run_smoke(vals, workers, candidate, reset))


def _load_smoke_env(path: Path) -> dict[str, str] | None:
    if not path.exists():
        _CONSOLE.print(f"[red]BLOCKED[/red]: smoke.env not found at {path}")
        _CONSOLE.print(
            "  Create it with: POSTGRES_DB=..., POSTGRES_USER=..."
            ", POSTGRES_PASSWORD=..."
        )
        return None
    vals: dict[str, str] = {}
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            vals[k.strip()] = v.strip()
    required = {"POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD"}
    missing = required - vals.keys()
    if missing:
        _CONSOLE.print(
            f"[red]BLOCKED[/red]: smoke.env missing required keys: {missing}"
        )
        return None
    return vals


def _apply_env(vals: dict[str, str], buffered: bool, warm_pool: bool) -> None:
    os.environ["DB__HOST"] = "127.0.0.1"
    os.environ["DB__PORT"] = "15432"
    os.environ["DB__NAME"] = vals["POSTGRES_DB"]
    os.environ["DB__USER"] = vals["POSTGRES_USER"]
    os.environ["DB__PASSWORD"] = vals["POSTGRES_PASSWORD"]
    os.environ["DB__SSL_MODE"] = "disable"
    os.environ.setdefault("SCRAPING__WORK_SERVER_TOKEN", "smoke-local-token")
    os.environ["SCRAPING__PLAYER_INFO_DISPATCH_BUFFER_ENABLED"] = (
        "true" if buffered else "false"
    )
    os.environ["SCRAPING__PLAYER_INFO_WARM_POOL_ENABLED"] = (
        "true" if (buffered and warm_pool) else "false"
    )
    os.environ["PGOPTIONS"] = f"-c search_path={_SEARCH_PATH}"


def _print_dry_run_summary(
    buffered: bool,
    warm_pool: bool,
    workers: int,
    candidate: str,
    smoke_env: Path,
    reset: bool,
    vals: dict[str, str],
) -> None:
    _CONSOLE.print("[bold]smoke-player-info — dry run[/bold]")
    _CONSOLE.print(f"  smoke_env : {smoke_env}")
    db_name = vals.get("POSTGRES_DB", "?")
    _CONSOLE.print(f"  DB target : 127.0.0.1:15432 / {db_name} (smoke only)")
    _CONSOLE.print(f"  candidate : {candidate}")
    _CONSOLE.print(f"  workers   : {workers}")
    _CONSOLE.print(f"  buffered  : {buffered}")
    _CONSOLE.print(f"  warm_pool : {warm_pool}")
    _CONSOLE.print(f"  reset     : {reset}")
    _CONSOLE.print(f"  search_path: {_SEARCH_PATH}")
    _CONSOLE.print("  POSTGRES_PASSWORD: [NOT PRINTED]")
    _CONSOLE.print(
        "[green]Dry run complete. No DB connection or scraper was started.[/green]"
    )


async def _run_smoke(
    vals: dict[str, str],
    workers: int,
    candidate: str,
    reset: bool,
) -> None:
    import asyncpg

    try:
        conn = await asyncpg.connect(
            host="127.0.0.1",
            port=15432,
            database=vals["POSTGRES_DB"],
            user=vals["POSTGRES_USER"],
            password=vals["POSTGRES_PASSWORD"],
            server_settings={"search_path": _SEARCH_PATH},
        )
    except Exception as exc:
        _CONSOLE.print(
            f"[red]BLOCKED[/red]: Cannot connect to smoke DB at 127.0.0.1:15432 — "
            f"{type(exc).__name__}"
        )
        raise typer.Exit(code=1) from exc

    try:
        try:
            ver = await conn.fetchval("SELECT version_num FROM alembic_version LIMIT 1")
            _CONSOLE.print(f"[green]schema[/green]: alembic_version={ver}")
        except Exception as exc:
            _CONSOLE.print(
                f"[red]BLOCKED[/red]: Cannot read alembic_version — "
                f"{type(exc).__name__}: {exc}"
            )
            raise typer.Exit(code=1) from exc

        other = await conn.fetchval(
            "SELECT COUNT(*) FROM sch_fbref_backend.tbl_player_urls "
            "WHERE url_type='profile' AND status IN ('PENDING','ACTIVE') "
            "AND next_scrape_at <= NOW() AND fk_player != $1",
            candidate,
        )
        if other > 0:
            _CONSOLE.print(
                f"[red]BLOCKED[/red]: {other} other eligible candidate(s) found. "
                "Scope is not bounded to a single candidate."
            )
            raise typer.Exit(code=1)

        if reset:
            await _reset_candidate(conn, candidate)

        sq_pre = await conn.fetchval(
            "SELECT COUNT(*) FROM sch_fbref_infra.scrape_queue "
            "WHERE url LIKE $1 AND job_type='player_info'",
            f"%/players/{candidate}/%",
        )
        pi_pre = await conn.fetchval(
            "SELECT COUNT(*) FROM sch_fbref_shared.tbl_player_info WHERE player_id=$1",
            candidate,
        )
        pu_pre = await conn.fetchrow(
            "SELECT status FROM sch_fbref_backend.tbl_player_urls "
            "WHERE fk_player=$1 AND url_type='profile'",
            candidate,
        )
        if sq_pre != 0 or pi_pre != 0 or not pu_pre or pu_pre["status"] != "PENDING":
            _CONSOLE.print(
                f"[red]BLOCKED[/red]: Pre-run gate failed — "
                f"sq={sq_pre} pi={pi_pre} "
                f"pu_status={pu_pre['status'] if pu_pre else 'MISSING'}"
            )
            raise typer.Exit(code=1)

        _CONSOLE.print(
            f"[green]pre-run gate PASS[/green]: candidate={candidate} "
            "sq=0 pi=0 status=PENDING"
        )
    finally:
        await conn.close()

    _CONSOLE.print(f"[bold]starting scraper[/bold]: workers={workers}")
    from scripts.scrape_player_info import main as scraper_main

    await scraper_main(workers=workers)

    conn2 = await asyncpg.connect(
        host="127.0.0.1",
        port=15432,
        database=vals["POSTGRES_DB"],
        user=vals["POSTGRES_USER"],
        password=vals["POSTGRES_PASSWORD"],
        server_settings={"search_path": _SEARCH_PATH},
    )
    try:
        await _verify_final(conn2, candidate)
    finally:
        await conn2.close()


async def _reset_candidate(conn: asyncpg.Connection, candidate: str) -> None:
    url_pat = f"%/players/{candidate}/%"
    r = await conn.execute(
        "DELETE FROM sch_fbref_infra.scrape_queue "
        "WHERE url LIKE $1 AND job_type='player_info'",
        url_pat,
    )
    _CONSOLE.print(f"  reset: scrape_queue {r}")
    r = await conn.execute(
        "DELETE FROM sch_fbref_shared.tbl_player_info WHERE player_id=$1",
        candidate,
    )
    _CONSOLE.print(f"  reset: tbl_player_info {r}")
    await conn.execute(
        "UPDATE sch_fbref_backend.tbl_player_urls "
        "SET status='PENDING', next_scrape_at=NOW()-INTERVAL '1 minute', "
        "last_scraped_at=NULL, last_scrape_status=NULL, retry_count=0, last_error=NULL "
        "WHERE fk_player=$1 AND url_type='profile'",
        candidate,
    )
    _CONSOLE.print("  reset: tbl_player_urls -> PENDING")


async def _verify_final(conn: asyncpg.Connection, candidate: str) -> None:
    url_pat = f"%/players/{candidate}/%"
    sq = await conn.fetch(
        "SELECT status, retry_count, completed_at FROM sch_fbref_infra.scrape_queue "
        "WHERE url LIKE $1 AND job_type='player_info'",
        url_pat,
    )
    stale = await conn.fetchval(
        "SELECT COUNT(*) FROM sch_fbref_infra.scrape_queue "
        "WHERE job_type='player_info' AND status='IN_PROGRESS'"
    )
    pi = await conn.fetchval(
        "SELECT COUNT(*) FROM sch_fbref_shared.tbl_player_info WHERE player_id=$1",
        candidate,
    )
    pu = await conn.fetchrow(
        "SELECT status, last_scrape_status FROM sch_fbref_backend.tbl_player_urls "
        "WHERE fk_player=$1 AND url_type='profile'",
        candidate,
    )
    dup_sq = await conn.fetchval(
        "SELECT COUNT(*) FROM ("
        "  SELECT url, COUNT(*) FROM sch_fbref_infra.scrape_queue "
        "  WHERE url LIKE $1 AND job_type='player_info' GROUP BY url HAVING COUNT(*)>1"
        ") x",
        url_pat,
    )
    dup_pi = await conn.fetchval(
        "SELECT COUNT(*) FROM ("
        "  SELECT player_id, COUNT(*) FROM sch_fbref_shared.tbl_player_info "
        "  WHERE player_id=$1 GROUP BY player_id HAVING COUNT(*)>1"
        ") x",
        candidate,
    )

    sq_ok = (
        len(sq) == 1
        and sq[0]["status"] == "DONE"
        and sq[0]["retry_count"] == 0
        and sq[0]["completed_at"] is not None
    )
    pu_ok = (
        pu is not None
        and pu["status"] == "ACTIVE"
        and pu["last_scrape_status"] == "SUCCESS"
    )
    pass_cond = (
        sq_ok and stale == 0 and pi == 1 and pu_ok and dup_sq == 0 and dup_pi == 0
    )

    if pass_cond:
        _CONSOLE.print(
            "[bold green]PASS[/bold green]: "
            "scrape_queue=DONE pi=1 stale=0 duplicates=0 tbl_player_urls=ACTIVE/SUCCESS"
        )
    else:
        sq_status = sq[0]["status"] if sq else "MISSING"
        _CONSOLE.print(
            f"[bold red]FAIL[/bold red]: "
            f"sq={sq_status} pi={pi} stale={stale} dup_sq={dup_sq} dup_pi={dup_pi} "
            f"pu_status={pu['status'] if pu else 'MISSING'} "
            f"pu_scrape_status={pu['last_scrape_status'] if pu else 'N/A'}"
        )
        raise typer.Exit(code=1)
