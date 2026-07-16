"""Preflight check orchestration for the sportcrawl pipeline."""
from __future__ import annotations

from rich.console import Console

from core.preflight.checks import (
    check_alembic_initialized,
    check_alembic_revision,
    check_db_reachable,
    check_schemas_exist,
    check_seed_data,
    check_stale_queue,
    check_tables_exist,
)
from core.preflight.renderer import render_check
from core.preflight.result import CheckResult

REQUIRED_HEAD = "p14g"


async def run_checks(dsn: str, phase: str, console: Console) -> list[CheckResult]:
    """Run all applicable checks for the given phase and return results."""
    results: list[CheckResult] = []

    checks = [
        check_db_reachable(dsn),
        check_alembic_initialized(dsn),
        check_alembic_revision(dsn, REQUIRED_HEAD),
        check_schemas_exist(dsn),
        check_tables_exist(dsn, phase),  # type: ignore[arg-type]
    ]

    for coro in checks:
        result = await coro
        render_check(result, console)
        results.append(result)
        if not result.passed and result.fatal:
            return results

    if phase in ("players", "player_info"):
        result = await check_seed_data(dsn, phase)  # type: ignore[arg-type]
        render_check(result, console)
        results.append(result)
        if not result.passed and result.fatal:
            return results

    result = await check_stale_queue(dsn)
    render_check(result, console)
    results.append(result)

    return results
