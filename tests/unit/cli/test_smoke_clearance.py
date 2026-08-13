"""CP1.6f.5-RED — Contract tests for a future smoke-clearance CLI harness.

Defines what smoke-clearance must look like when implemented (CP1.6f.6).

The command does not exist yet. All tests in this file are expected to FAIL
until implementation is complete.

Contract summary:
- clearance-only dry-run: no DB, no browser, no scrape_queue, no player scraper.
- workers fixed to 1.
- dry-run defaults to safe/read-only behavior.
- output is sanitized — no token, no cf_clearance, no DSN, no profile path.
- independent of smoke-player-info and asyncpg.

Static source inspection only where noted. No browser, network, DB, or Docker.
"""

from __future__ import annotations

import re
from pathlib import Path

from typer.testing import CliRunner

from cli.main import app

runner = CliRunner()

_CLI_MAIN = Path(__file__).parents[3] / "cli" / "main.py"

_SENSITIVE_TERMS = (
    "cf_clearance",
    "cookies",
    "POSTGRES_PASSWORD",
    "DB__PASSWORD",
    "DATABASE_URL",
    "profile_path",
    "cdp",
    "raw_html",
    "dsn",
)

_SAFE_DRY_RUN_TERMS = (
    "clearance-only",
    "/api/clearance",
    "disable_task_polling",
    "workers",
)


# ---------------------------------------------------------------------------
# 1. Command registration
# ---------------------------------------------------------------------------


class TestCommandRegistration:
    def test_smoke_clearance_command_registered(self) -> None:
        """smoke-clearance must be registered in the Typer app.

        Expected RED: command is absent from registered_commands.
        """
        names = [c.name for c in app.registered_commands]
        assert "smoke-clearance" in names, (
            "smoke-clearance must be registered in the Typer app. "
            "Implement the command in cli/main.py."
        )


# ---------------------------------------------------------------------------
# 2. Dry-run exits zero
# ---------------------------------------------------------------------------


class TestDryRun:
    def test_smoke_clearance_dry_run_exits_zero(self) -> None:
        """smoke-clearance --dry-run must exit with code 0.

        Dry-run must be safe by default — no live state, no DB, no browser.
        Expected RED: command not registered, invocation fails.
        """
        result = runner.invoke(app, ["smoke-clearance", "--dry-run"])
        assert result.exit_code == 0, (
            f"smoke-clearance --dry-run exited {result.exit_code}. "
            f"Output: {result.output}"
        )

    def test_smoke_clearance_dry_run_is_default_mode(self) -> None:
        """Invoking smoke-clearance without arguments must behave as dry-run.

        The harness must default to safe/read-only. Unsafe execution must
        require an explicit flag (e.g. --execute or absence of --dry-run).
        Expected RED: command not registered.
        """
        result = runner.invoke(app, ["smoke-clearance"])
        assert result.exit_code == 0, (
            f"smoke-clearance (no args) exited {result.exit_code}. "
            "Default invocation must be safe/dry-run. "
            f"Output: {result.output}"
        )


# ---------------------------------------------------------------------------
# 3. Dry-run output is clearance-only
# ---------------------------------------------------------------------------


class TestDryRunClearanceOnlyOutput:
    def test_smoke_clearance_dry_run_is_clearance_only(self) -> None:
        """Dry-run output must indicate clearance-only scope.

        Output must reference at least one of: clearance-only, /api/clearance,
        disable_task_polling, workers: 1. This proves the command is not
        silently reusing the player-info flow.
        Expected RED: command not registered.
        """
        result = runner.invoke(app, ["smoke-clearance", "--dry-run"])
        output_lower = result.output.lower()
        found = any(term.lower() in output_lower for term in _SAFE_DRY_RUN_TERMS)
        assert found, (
            "smoke-clearance --dry-run output must reference at least one of "
            f"{_SAFE_DRY_RUN_TERMS}. Got: {result.output!r}"
        )


# ---------------------------------------------------------------------------
# 4. Sensitive values are not printed
# ---------------------------------------------------------------------------


class TestSensitiveOutputSanitization:
    def test_smoke_clearance_dry_run_sanitizes_sensitive_values(self) -> None:
        """Dry-run output must not include sensitive terms.

        No token, cf_clearance, raw cookie, profile path, CDP data, DSN,
        DB password, or raw HTML may appear in stdout/stderr.
        Expected RED: command not registered.
        """
        result = runner.invoke(
            app,
            ["smoke-clearance", "--dry-run"],
            env={"WORK_SERVER_TOKEN": "placeholder-token-do-not-log"},
        )
        output_lower = result.output.lower()
        for term in _SENSITIVE_TERMS:
            assert term.lower() not in output_lower, (
                f"Sensitive term '{term}' found in smoke-clearance dry-run output. "
                "Sanitize all sensitive values before printing."
            )

    def test_smoke_clearance_dry_run_does_not_print_token_placeholder(self) -> None:
        """The work_server_token placeholder value must not appear verbatim in output.

        Expected RED: command not registered.
        """
        result = runner.invoke(
            app,
            ["smoke-clearance", "--dry-run"],
            env={"WORK_SERVER_TOKEN": "placeholder-token-do-not-log"},
        )
        assert "placeholder-token-do-not-log" not in result.output, (
            "Token value appeared verbatim in dry-run output. "
            "Never log token values."
        )


# ---------------------------------------------------------------------------
# 5. Workers fixed to 1
# ---------------------------------------------------------------------------


class TestWorkerCount:
    def test_smoke_clearance_default_workers_is_one(self) -> None:
        """smoke-clearance must default to workers=1.

        Clearance-only smoke runs a single browser profile. Multi-worker
        parallelism is not safe for the smoke harness.
        Expected RED: command not registered.
        """
        result = runner.invoke(app, ["smoke-clearance", "--dry-run"])
        assert result.exit_code == 0, (
            f"smoke-clearance --dry-run failed: {result.output}"
        )
        assert "1" in result.output or "workers" in result.output.lower(), (
            "Dry-run output must confirm workers=1 configuration."
        )

    def test_smoke_clearance_accepts_workers_one(self) -> None:
        """--workers 1 must be accepted without error.

        Expected RED: command not registered.
        """
        result = runner.invoke(app, ["smoke-clearance", "--dry-run", "--workers", "1"])
        assert result.exit_code == 0, (
            f"smoke-clearance --dry-run --workers 1 failed: {result.output}"
        )

    def test_smoke_clearance_rejects_workers_greater_than_one(self) -> None:
        """--workers >1 must be rejected or print an error.

        Clearance smoke is single-worker. Multi-worker invocation is a
        configuration error.
        Expected RED: command not registered.
        """
        result = runner.invoke(app, ["smoke-clearance", "--dry-run", "--workers", "2"])
        assert result.exit_code != 0 or "error" in result.output.lower(), (
            "smoke-clearance must reject --workers 2. "
            "Only workers=1 is permitted for clearance smoke."
        )


# ---------------------------------------------------------------------------
# 6. No DB env required
# ---------------------------------------------------------------------------


class TestNoDatabaseDependency:
    def test_smoke_clearance_does_not_require_db_env(self) -> None:
        """Dry-run must succeed without POSTGRES_* or DB__* environment variables.

        Clearance smoke must not touch the database. DB env must be optional.
        Expected RED: command not registered.
        """
        import os

        db_keys = [
            k for k in os.environ
            if k.startswith(("POSTGRES_", "DB__", "DATABASE_URL"))
        ]
        env_override = {k: "" for k in db_keys}

        result = runner.invoke(
            app,
            ["smoke-clearance", "--dry-run"],
            env=env_override,
        )
        assert result.exit_code == 0, (
            f"smoke-clearance --dry-run requires DB env but must not. "
            f"Exit code: {result.exit_code}. Output: {result.output}"
        )

    def test_smoke_clearance_does_not_require_smoke_env_file(self) -> None:
        """Dry-run must succeed without a smoke.env file.

        smoke-player-info requires smoke.env. smoke-clearance must not.
        Expected RED: command not registered.
        """
        result = runner.invoke(app, ["smoke-clearance", "--dry-run"])
        assert result.exit_code == 0, (
            f"smoke-clearance --dry-run failed without smoke.env: {result.output}"
        )


# ---------------------------------------------------------------------------
# 7. No smoke-player-info reuse (static source inspection)
# ---------------------------------------------------------------------------


class TestNoSmokePlayerInfoReuse:
    def test_smoke_clearance_does_not_reuse_smoke_player_info(self) -> None:
        """smoke-clearance must not be implemented by delegating to smoke-player-info.

        Static inspection of cli/main.py.
        When smoke-clearance is implemented, its handler must not call or import
        smoke_player_info or scripts.scrape_player_info.
        Current state: command absent — test fails on registration check.
        """
        names = [c.name for c in app.registered_commands]
        assert "smoke-clearance" in names, (
            "smoke-clearance not yet registered — implement without reusing"
            " smoke-player-info."
        )
        src = _CLI_MAIN.read_text(encoding="utf-8")
        # Locate the smoke_clearance handler body.
        m = re.search(
            r"(?:async\s+)?def\s+smoke_clearance\s*\([^)]*\)\s*->"
            r".*?(?=\n(?:@app|def |\Z))",
            src,
            re.DOTALL,
        )
        assert m, "smoke_clearance handler function not found in cli/main.py."
        body = m.group(0)
        assert "smoke_player_info" not in body, (
            "smoke_clearance handler must not call smoke_player_info."
        )
        assert "scrape_player_info" not in body, (
            "smoke_clearance handler must not reference scrape_player_info."
        )

    def test_smoke_clearance_does_not_import_asyncpg(self) -> None:
        """smoke-clearance handler must not import asyncpg.

        asyncpg implies a live DB connection. Clearance smoke is DB-free.
        Current state: command absent — fails on registration check.
        """
        names = [c.name for c in app.registered_commands]
        assert "smoke-clearance" in names, (
            "smoke-clearance not yet registered — implement without asyncpg."
        )
        src = _CLI_MAIN.read_text(encoding="utf-8")
        m = re.search(
            r"(?:async\s+)?def\s+smoke_clearance\s*\([^)]*\)\s*->"
            r".*?(?=\n(?:@app|def |\Z))",
            src,
            re.DOTALL,
        )
        assert m, "smoke_clearance handler function not found in cli/main.py."
        body = m.group(0)
        assert "asyncpg" not in body, (
            "smoke_clearance handler must not import or reference asyncpg. "
            "Clearance smoke is DB-free."
        )

    def test_smoke_clearance_does_not_reference_scrape_queue(self) -> None:
        """smoke-clearance handler must not reference scrape_queue.

        scrape_queue implies DB mutations. Clearance smoke must not touch it.
        Current state: command absent — fails on registration check.
        """
        names = [c.name for c in app.registered_commands]
        assert "smoke-clearance" in names, (
            "smoke-clearance not yet registered — implement without scrape_queue."
        )
        src = _CLI_MAIN.read_text(encoding="utf-8")
        m = re.search(
            r"(?:async\s+)?def\s+smoke_clearance\s*\([^)]*\)\s*->"
            r".*?(?=\n(?:@app|def |\Z))",
            src,
            re.DOTALL,
        )
        assert m, "smoke_clearance handler function not found in cli/main.py."
        body = m.group(0)
        assert "scrape_queue" not in body, (
            "smoke_clearance handler must not reference scrape_queue. "
            "Clearance smoke is queue-free."
        )
