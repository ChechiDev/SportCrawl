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

MINIMUM_REVISION: dict[str, str] = {
    "countries": "p10d_add_fk_ondelete",
    "players": "p11e_move_player_discovery_to_infra",
    "player_info": REQUIRED_HEAD,
}


async def run_checks(dsn: str, phase: str, console: Console) -> list[CheckResult]:
    """Run all applicable checks for the given phase and return results."""
    results: list[CheckResult] = []

    check_fns = [
        lambda: check_db_reachable(dsn),
        lambda: check_alembic_initialized(dsn),
        lambda: check_alembic_revision(dsn, MINIMUM_REVISION.get(phase, REQUIRED_HEAD)),
        lambda: check_schemas_exist(dsn),
        lambda: check_tables_exist(dsn, phase),  # type: ignore[arg-type]
    ]

    for fn in check_fns:
        result = await fn()
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
