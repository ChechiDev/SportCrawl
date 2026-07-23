"""Preflight check orchestration for the sportcrawl pipeline."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path

from rich.console import Console

from core.preflight.checks import (
    check_alembic_initialized,
    check_alembic_revision,
    check_country_squads_data,
    check_db_reachable,
    check_schemas_exist,
    check_seed_data,
    check_stale_queue,
    check_tables_exist,
)
from core.preflight.renderer import render_check, render_compact
from core.preflight.result import CheckResult

REQUIRED_HEAD = "p16b"
_CHECK_DISPLAY_DELAY_S = 1.5

MINIMUM_REVISION: dict[str, str] = {
    "countries": "p10d_add_fk_ondelete",
    "players": "p16b",
    "player_info": "p16b",
    "club_teams": "p16b",
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

    async def _run(fn: Callable[[], Awaitable[CheckResult]], label: str) -> CheckResult:
        console.print(f"  [dim]→[/dim]  [white]{label}[/white]", end="\r")
        await asyncio.sleep(_CHECK_DISPLAY_DELAY_S)
        result = await fn()
        return result

    check_fns = [
        (lambda: check_db_reachable(dsn), "Checking DB connection..."),
        (lambda: check_alembic_initialized(dsn), "Database migrations initialized..."),
        (
            lambda: check_alembic_revision(
                dsn, MINIMUM_REVISION.get(phase, REQUIRED_HEAD)
            ),
            "Checking DB revision...",
        ),
        (lambda: check_schemas_exist(dsn), "Checking schemas..."),
        (lambda: check_tables_exist(dsn, phase), "Checking tables..."),  # type: ignore[arg-type]  # noqa: E501
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
                results[-1] = result  # replace failed entry with fixed result
                if not result.passed:
                    if compact:
                        render_compact(results, console)
                    return results
            else:
                if compact:
                    render_compact(results, console)
                return results

    if phase in ("players", "player_info", "club_teams"):
        result = await _run(
            lambda: check_seed_data(dsn, phase),  # type: ignore[arg-type]
            "Checking seed data...",
        )
        if result.passed:
            _render(result)
        # On failure: suppress render — caller handles inline seeding display
        results.append(result)

        result = await _run(
            lambda: check_country_squads_data(dsn), "Checking country squads..."
        )
        if result.passed:
            _render(result)
        results.append(result)

        seed_failures = [r for r in results if not r.passed and r.fatal]
        if seed_failures:
            if compact:
                render_compact(results, console)
            return results

    result = await check_stale_queue(dsn)
    if not result.passed:
        _render(result)
    results.append(result)

    if compact:
        render_compact(results, console)

    return results
