"""Preflight check orchestration for the sportcrawl pipeline."""
from __future__ import annotations

import asyncio
from pathlib import Path

from rich.console import Console

from core.preflight.checks import (
    check_alembic_initialized,
    check_alembic_revision,
    check_clubs_data,
    check_db_reachable,
    check_schemas_exist,
    check_seed_data,
    check_stale_queue,
    check_tables_exist,
)
from core.preflight.renderer import render_check, render_compact
from core.preflight.result import CheckResult

REQUIRED_HEAD = "p15a"

MINIMUM_REVISION: dict[str, str] = {
    "countries": "p10d_add_fk_ondelete",
    "players": "p11e",
    "player_info": REQUIRED_HEAD,
}

_ALEMBIC_INI = Path(__file__).parent.parent.parent / "alembic.ini"


async def _run_migrations(console: Console) -> None:
    console.print("  --> Running: alembic upgrade head ...")
    proc = await asyncio.create_subprocess_exec(
        "uv", "run", "alembic", "-c", str(_ALEMBIC_INI), "upgrade", "head",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        msg = f"  [bold red]FAIL[/bold red] Migration failed:\n{stderr.decode()}"
        console.print(msg)
        raise SystemExit(1)
    console.print("  [bold green]OK  [/bold green] Migrations applied.")


async def run_checks(
    dsn: str, phase: str, console: Console, *, compact: bool = False
) -> list[CheckResult]:
    """Run all applicable checks for the given phase and return results."""
    results: list[CheckResult] = []

    def _render(result: CheckResult) -> None:
        if not compact:
            render_check(result, console)

    async def _run(fn, label: str) -> CheckResult:  # type: ignore[no-untyped-def]
        console.print(f"  [dim]→[/dim]  [white]{label}[/white]", end="\r")
        await asyncio.sleep(1.5)
        result = await fn()  # type: ignore[no-untyped-call]
        return result

    check_fns = [
        (lambda: check_db_reachable(dsn), "Checking DB connection..."),
        (lambda: check_alembic_initialized(dsn), "Database migrations initialized..."),
        (lambda: check_alembic_revision(dsn, MINIMUM_REVISION.get(phase, REQUIRED_HEAD)), "Checking DB revision..."),
        (lambda: check_schemas_exist(dsn), "Checking schemas..."),
        (lambda: check_tables_exist(dsn, phase), "Checking tables..."),  # type: ignore[arg-type]
    ]

    for fn, label in check_fns:
        result = await _run(fn, label)
        _render(result)
        results.append(result)
        if not result.passed and result.fatal:
            if result.name == "Alembic revision":
                await _run_migrations(console)
                result = await check_alembic_revision(
                    dsn, MINIMUM_REVISION.get(phase, REQUIRED_HEAD)
                )
                _render(result)
                results.append(result)
                if not result.passed:
                    if compact:
                        render_compact(results, console)
                    return results
            else:
                if compact:
                    render_compact(results, console)
                return results

    if phase in ("players", "player_info"):
        result = await _run(lambda: check_seed_data(dsn, phase), "Checking seed data...")  # type: ignore[arg-type]
        if result.passed:
            _render(result)
        # On failure: suppress render — caller handles inline seeding display
        results.append(result)
        if not result.passed and result.fatal:
            if compact:
                render_compact(results, console)
            return results

    if phase in ("players", "player_info"):
        result = await _run(lambda: check_clubs_data(dsn), "Checking clubs data...")
        _render(result)
        results.append(result)

    result = await check_stale_queue(dsn)
    if not result.passed:
        _render(result)
    results.append(result)

    if compact:
        render_compact(results, console)

    return results
