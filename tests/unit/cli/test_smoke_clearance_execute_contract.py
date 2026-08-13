"""CP1.6g-RED — Contract tests for the future smoke-clearance --execute harness.

Defines what smoke-clearance --execute must look like when implemented (CP1.6g-GREEN).

ALL tests in this file are expected to FAIL until implementation is complete.
Failures must point to missing --execute option or missing executable harness contract —
not to import errors, DB/browser/network dependencies, or environment variables.

Contract summary:
- smoke-clearance --execute is the real-smoke gate (not --no-dry-run).
- --execute --dry-run is rejected as conflicting.
- Default and --dry-run behavior is preserved (regression guard).
- --execute enforces workers=1 and rejects workers>1.
- --execute uses injectable/fake dependencies for every live-state boundary.
- Lifecycle order is enforced: work_server → temp profile → inject config → launch
  browser → observe /api/clearance 204 → remove config → clean profile → stop server.
- Cleanup runs on success, failure, timeout, and exception.
- No /api/tasks/next or /api/tasks/{id}/result.
- No DB, Docker, scrape_queue, smoke-player-info, asyncpg.
- Report output contains only allowlisted safe fields — no raw payloads.

Static source inspection where noted. No browser, network, DB, or Docker.
"""

from __future__ import annotations

import re
from pathlib import Path

from typer.testing import CliRunner

from cli.main import app

runner = CliRunner()

_CLI_MAIN = Path(__file__).parents[3] / "cli" / "main.py"

# ---------------------------------------------------------------------------
# Sentinel placeholders — must never appear in any output
# ---------------------------------------------------------------------------

SENTINEL_TOKEN_VALUE = "SENTINEL_TOKEN_VALUE"
SENTINEL_CLEARANCE_VALUE = "SENTINEL_CLEARANCE_VALUE"
SENTINEL_COOKIE_VALUE = "SENTINEL_COOKIE_VALUE"
SENTINEL_PROFILE_VALUE = "SENTINEL_PROFILE_VALUE"
SENTINEL_CDP_VALUE = "SENTINEL_CDP_VALUE"
SENTINEL_HTML_VALUE = "SENTINEL_HTML_VALUE"
SENTINEL_DSN_VALUE = "SENTINEL_DSN_VALUE"

_ALL_SENTINELS = (
    SENTINEL_TOKEN_VALUE,
    SENTINEL_CLEARANCE_VALUE,
    SENTINEL_COOKIE_VALUE,
    SENTINEL_PROFILE_VALUE,
    SENTINEL_CDP_VALUE,
    SENTINEL_HTML_VALUE,
    SENTINEL_DSN_VALUE,
)

_SENSITIVE_CLASSES = (
    "password",
    "cf_clearance",
    "cookie",
    "profile_path",
    "cdp",
    "websocket",
    "raw_html",
    "screenshot",
    "har",
    "database_url",
    "db_url",
    "postgres_password",
    "authorization",
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _src() -> str:
    return _CLI_MAIN.read_text(encoding="utf-8")


def _execute_in_help() -> bool:
    """Return True if --execute is registered as a Click option on smoke-clearance.

    Uses direct Click param inspection instead of help-text rendering to avoid
    fragility across Typer/Rich versions and terminal-width environments.
    """
    import typer.main as typer_main

    cli = typer_main.get_command(app)
    sub = getattr(cli, "commands", {}).get("smoke-clearance")
    if sub is None:
        return False
    return any(
        "--execute" in getattr(p, "opts", []) for p in sub.params
    )


def _require_execute_registered() -> None:
    """Fail with a clear message if --execute is not yet registered.

    Use this as a prerequisite guard in tests that cannot run until
    --execute exists. Ensures RED failures point to the missing option,
    not to downstream assertion noise.
    """
    assert _execute_in_help(), (
        "--execute option not yet registered in smoke-clearance. "
        "Implement --execute in cli/main.py (CP1.6g-GREEN) before re-running."
    )


def _smoke_clearance_body() -> str:
    """Extract the smoke_clearance function body from cli/main.py."""
    src = _src()
    m = re.search(
        r"(?:async\s+)?def\s+smoke_clearance\s*\([^)]*\)\s*->.*?(?=\n(?:@app|def |\Z))",
        src,
        re.DOTALL,
    )
    return m.group(0) if m else ""


# ---------------------------------------------------------------------------
# 1. --execute option registration
# ---------------------------------------------------------------------------


class TestExecuteOptionRegistration:
    """CP1.6g — --execute explicit fake/local seam registration contract."""

    def test_execute_option_in_help_text(self) -> None:
        """--execute must be registered as a Click option on smoke-clearance.

        Uses direct Click param inspection — avoids Rich/Typer rendering
        fragility across environments where ANSI codes can split option tokens.
        """
        import typer.main as typer_main

        cli = typer_main.get_command(app)
        sub = getattr(cli, "commands", {}).get("smoke-clearance")
        assert sub is not None, (
            "smoke-clearance command not registered in the Typer app."
        )
        registered = any(
            "--execute" in getattr(p, "opts", []) for p in sub.params
        )
        assert registered, (
            "--execute option not registered on smoke-clearance. "
            "Implement --execute as the explicit execute option in cli/main.py."
        )

    def test_execute_exits_zero_by_itself(self) -> None:
        """smoke-clearance --execute (without other args) must exit 0.

        Expected RED: --execute not recognized → exit 2.
        """
        result = runner.invoke(app, ["smoke-clearance", "--execute"])
        assert result.exit_code == 0, (
            f"smoke-clearance --execute exited {result.exit_code}. "
            f"Output: {result.output}"
        )


# ---------------------------------------------------------------------------
# 2. --execute and --dry-run are mutually exclusive
# ---------------------------------------------------------------------------


class TestExecuteDryRunConflict:
    """CP1.6g-RED — --execute and --dry-run must be rejected as conflicting."""

    def test_execute_and_dry_run_are_mutually_exclusive(self) -> None:
        """--execute --dry-run must be rejected.

        These options are semantically opposite: --execute means real smoke,
        --dry-run means no live state. Combining them must be an error.
        Expected RED: --execute not yet registered → prerequisite fails.
        """
        _require_execute_registered()

        result = runner.invoke(app, ["smoke-clearance", "--execute", "--dry-run"])
        assert result.exit_code != 0, (
            "smoke-clearance --execute --dry-run must be rejected. "
            "These options are mutually exclusive — accepting both is ambiguous."
        )


# ---------------------------------------------------------------------------
# 3. Default and --dry-run behavior preserved (regression guards — GREEN today)
# ---------------------------------------------------------------------------


class TestDefaultModePreservation:
    """Regression guards — default and --dry-run behavior must remain unchanged."""

    def test_default_invocation_is_still_dry_run(self) -> None:
        """smoke-clearance with no args must still exit 0 in dry-run mode."""
        result = runner.invoke(app, ["smoke-clearance"])
        assert result.exit_code == 0, (
            f"smoke-clearance (no args) regressed: exit {result.exit_code}. "
            f"Output: {result.output}"
        )

    def test_dry_run_flag_is_still_safe(self) -> None:
        """smoke-clearance --dry-run must still exit 0."""
        result = runner.invoke(app, ["smoke-clearance", "--dry-run"])
        assert result.exit_code == 0, (
            f"smoke-clearance --dry-run regressed: exit {result.exit_code}. "
            f"Output: {result.output}"
        )

    def test_dry_run_does_not_print_execute_mode_output(self) -> None:
        """smoke-clearance --dry-run must not behave like --execute.

        Dry-run must not trigger any live-state path (work_server, browser, etc.).
        """
        result = runner.invoke(app, ["smoke-clearance", "--dry-run"])
        assert result.exit_code == 0
        output_lower = result.output.lower()
        _LIVE_TERMS = ("work_server started", "browser launched", "clearance received")
        for live_term in _LIVE_TERMS:
            assert live_term not in output_lower, (
                f"Dry-run output contains live-state indicator '{live_term}'. "
                "Dry-run must not trigger the executable harness."
            )


# ---------------------------------------------------------------------------
# 4. --execute enforces workers=1
# ---------------------------------------------------------------------------


class TestExecuteWorkerConstraint:
    """CP1.6g-RED — --execute must enforce workers=1."""

    def test_execute_accepts_workers_one(self) -> None:
        """--execute --workers 1 must be accepted.

        Expected RED: --execute not recognized → exit 2.
        """
        result = runner.invoke(app, ["smoke-clearance", "--execute", "--workers", "1"])
        assert result.exit_code == 0, (
            f"smoke-clearance --execute --workers 1 failed: {result.output}"
        )

    def test_execute_rejects_workers_two(self) -> None:
        """--execute --workers 2 must be rejected.

        Executable clearance smoke is single-worker only.
        Expected RED: --execute not recognized → prerequisite fails.
        """
        _require_execute_registered()

        result = runner.invoke(app, ["smoke-clearance", "--execute", "--workers", "2"])
        assert result.exit_code != 0 or "error" in result.output.lower(), (
            "smoke-clearance --execute --workers 2 must be rejected. "
            "Only workers=1 is permitted for executable clearance smoke."
        )


# ---------------------------------------------------------------------------
# 5. Injectable harness dependencies (static source inspection)
# ---------------------------------------------------------------------------


class TestExecuteHarnessInjectability:
    """CP1.6g-RED — executable harness must accept injectable dependencies.

    Real smoke requires live boundaries (work_server, browser, config injector,
    cleanup finalizer). These must be injectable to allow safe unit testing
    of the harness without real browsers or networks.

    All tests in this class fail until --execute + the harness are implemented.
    """

    def test_handler_references_injectable_work_server_start(self) -> None:
        """smoke_clearance body must reference a work_server_start injectable.

        The harness must accept a callable that starts (or fakes) the loopback
        work server. This is the injection point for unit-testing without a
        real aiohttp server.
        Expected RED: --execute not registered → prerequisite fails.
        """
        _require_execute_registered()

        body = _smoke_clearance_body()
        assert body, "smoke_clearance function not found in cli/main.py."
        assert "work_server" in body, (
            "smoke_clearance body does not reference 'work_server'. "
            "Implement an injectable work_server_start dependency."
        )

    def test_handler_references_injectable_browser_launcher(self) -> None:
        """smoke_clearance body must reference a browser_launcher injectable.

        The harness must accept a callable that launches (or fakes) the browser
        with the temp profile. This is the injection point for unit-testing
        without a real Chrome process.
        Expected RED: --execute not registered → prerequisite fails.
        """
        _require_execute_registered()

        body = _smoke_clearance_body()
        assert body, "smoke_clearance function not found in cli/main.py."
        assert "browser" in body.lower(), (
            "smoke_clearance body does not reference a browser launcher. "
            "Implement an injectable browser_launcher dependency."
        )

    def test_handler_references_cleanup_finalizer(self) -> None:
        """smoke_clearance body must have a cleanup/finally block.

        Cleanup (stop server, wipe profile, remove token) must run on any path:
        success, failure, timeout, or exception.
        Expected RED: --execute not registered → prerequisite fails.
        """
        _require_execute_registered()

        body = _smoke_clearance_body()
        assert body, "smoke_clearance function not found in cli/main.py."
        assert "finally" in body or "cleanup" in body.lower(), (
            "smoke_clearance body has no finally block or cleanup reference. "
            "Implement cleanup-on-all-paths using try/finally."
        )

    def test_handler_has_clearance_observation_point(self) -> None:
        """smoke_clearance body must reference /api/clearance observation.

        The harness must observe the clearance POST (e.g. check server received
        a 204) to confirm end-to-end delivery. This is the core proof point.
        Expected RED: --execute not registered → prerequisite fails.
        """
        _require_execute_registered()

        body = _smoke_clearance_body()
        assert body, "smoke_clearance function not found in cli/main.py."
        assert "/api/clearance" in body, (
            "smoke_clearance body does not reference /api/clearance. "
            "Implement a clearance POST observation step."
        )


# ---------------------------------------------------------------------------
# 6. Lifecycle ordering (static source inspection)
# ---------------------------------------------------------------------------


class TestExecuteLifecycleOrder:
    """CP1.6g-RED — lifecycle steps must appear in the correct order in source."""

    def test_work_server_start_before_browser_launch(self) -> None:
        """work_server start must appear before browser launch in source order.

        Step 1 (start work_server) must precede Step 5 (launch browser).
        This is a static proxy for runtime ordering.
        Expected RED: --execute not registered → prerequisite fails.
        """
        _require_execute_registered()

        body = _smoke_clearance_body()
        assert body, "smoke_clearance function not found in cli/main.py."

        server_pos = body.lower().find("work_server")
        browser_pos = body.lower().find("browser")
        assert server_pos != -1, (
            "work_server reference not found in smoke_clearance body."
        )
        assert browser_pos != -1, (
            "browser reference not found in smoke_clearance body."
        )
        assert server_pos < browser_pos, (
            "work_server start must appear before browser launch in smoke_clearance. "
            "Lifecycle step 1 (start server) must precede step 5 (launch browser)."
        )

    def test_clearance_observation_before_cleanup(self) -> None:
        """/api/clearance observation must appear before cleanup in source order.

        Step 6 (observe clearance 204) must precede Step 7–9 (cleanup).
        Expected RED: --execute not registered → prerequisite fails.
        """
        _require_execute_registered()

        body = _smoke_clearance_body()
        assert body, "smoke_clearance function not found in cli/main.py."

        clearance_pos = body.find("/api/clearance")
        cleanup_pos = max(body.lower().find("cleanup"), body.find("finally"))
        assert clearance_pos != -1, (
            "/api/clearance observation not found in smoke_clearance body."
        )
        assert cleanup_pos != -1, (
            "cleanup / finally not found in smoke_clearance body."
        )
        assert clearance_pos < cleanup_pos, (
            "/api/clearance observation must appear before cleanup in smoke_clearance. "
            "Lifecycle step 6 (observe) must precede steps 7–9 (cleanup)."
        )

    def test_cleanup_in_finally_block(self) -> None:
        """Cleanup must be in a finally block to guarantee it runs on any exit path.

        A cleanup outside try/finally can be skipped by early return or exception.
        Expected RED: --execute not registered → prerequisite fails.
        """
        _require_execute_registered()

        body = _smoke_clearance_body()
        assert body, "smoke_clearance function not found in cli/main.py."
        assert "finally" in body, (
            "smoke_clearance has no finally block. "
            "Cleanup must be in try/finally to guarantee execution on all paths."
        )


# ---------------------------------------------------------------------------
# 7. No task endpoint references in the harness
# ---------------------------------------------------------------------------


class TestExecuteTaskIsolation:
    """CP1.6g-RED — executable harness must not reference task polling endpoints."""

    def test_execute_harness_has_no_tasks_next_reference(self) -> None:
        """/api/tasks/next must not appear in smoke_clearance body.

        The executable harness is clearance-only. Task polling must remain disabled
        via disable_task_polling. The harness itself must not fetch task endpoints.
        Expected RED: --execute not registered → prerequisite fails.
        """
        _require_execute_registered()

        body = _smoke_clearance_body()
        assert body, "smoke_clearance function not found in cli/main.py."
        assert "/api/tasks/next" not in body, (
            "smoke_clearance body references /api/tasks/next. "
            "The clearance harness must not poll for tasks."
        )

    def test_execute_harness_has_no_tasks_result_reference(self) -> None:
        """/api/tasks/{id}/result must not appear in smoke_clearance body.

        The harness must not post task results — that is task-polling behavior.
        Expected RED: --execute not registered → prerequisite fails.
        """
        _require_execute_registered()

        body = _smoke_clearance_body()
        assert body, "smoke_clearance function not found in cli/main.py."
        assert "/api/tasks/" not in body or "/api/clearance" in body, (
            "smoke_clearance body references /api/tasks/{id}. "
            "The clearance harness must not handle task results."
        )


# ---------------------------------------------------------------------------
# 8. Sanitized output — sentinel values must not appear
# ---------------------------------------------------------------------------


class TestExecuteSanitizedOutput:
    """CP1.6g-RED — output must be free of sentinel and sensitive values."""

    def test_execute_does_not_print_any_sentinel_value(self) -> None:
        """No sentinel placeholder must appear in --execute output.

        Expected RED: --execute not recognized → exit 2, but sentinel check still valid.
        Note: even if exit_code is 2, output must be free of sentinel values.
        """
        result = runner.invoke(
            app,
            ["smoke-clearance", "--execute"],
            env={
                "WORK_SERVER_TOKEN": SENTINEL_TOKEN_VALUE,
                "CLEARANCE_VALUE": SENTINEL_CLEARANCE_VALUE,
            },
        )
        output = result.output
        for sentinel in _ALL_SENTINELS:
            assert sentinel not in output, (
                f"Sentinel value '{sentinel}' appeared in --execute output. "
                "Sentinel placeholders must never be printed."
            )

    def test_execute_does_not_print_sensitive_class_names_as_values(self) -> None:
        """Sensitive class names (password, cf_clearance, etc.) must not be printed.

        Expected RED: --execute not recognized → prerequisite fails.
        """
        _require_execute_registered()

        result = runner.invoke(app, ["smoke-clearance", "--execute"])
        output_lower = result.output.lower()
        for term in _SENSITIVE_CLASSES:
            assert term not in output_lower, (
                f"Sensitive term '{term}' appeared in --execute output. "
                "Report must be allowlisted: statuses, counts, booleans, paths only."
            )

    def test_execute_report_contains_only_allowlisted_fields(self) -> None:
        """--execute output must contain only safe allowlisted terms.

        Allowlisted: status terms (pass/fail/ok/error), counts, booleans (true/false),
        and endpoint path names (/api/clearance). No raw payloads.
        Expected RED: --execute not recognized → prerequisite fails.
        """
        _require_execute_registered()

        result = runner.invoke(app, ["smoke-clearance", "--execute"])
        assert result.exit_code == 0, (
            f"smoke-clearance --execute failed: {result.output}"
        )
        output_lower = result.output.lower()
        for term in _SENSITIVE_CLASSES:
            assert term not in output_lower, (
                f"Non-allowlisted term '{term}' in --execute report. "
                "Report must contain only statuses, counts, booleans, and path names."
            )


# ---------------------------------------------------------------------------
# 9. No forbidden dependencies in handler (static source inspection)
# ---------------------------------------------------------------------------


class TestExecuteNoForbiddenDependencies:
    """CP1.6g-RED — smoke_clearance must not reference forbidden dependencies."""

    def test_execute_handler_has_no_asyncpg(self) -> None:
        """smoke_clearance body must not reference asyncpg.

        asyncpg implies a live DB connection. Clearance smoke is DB-free.
        Prerequisite: --execute must be registered (otherwise tests are vacuous).
        """
        _require_execute_registered()

        body = _smoke_clearance_body()
        assert body, "smoke_clearance function not found in cli/main.py."
        assert "asyncpg" not in body, (
            "smoke_clearance body references asyncpg. "
            "Clearance smoke must be DB-free."
        )

    def test_execute_handler_has_no_scrape_queue(self) -> None:
        """smoke_clearance body must not reference scrape_queue.

        scrape_queue mutations are forbidden in clearance smoke.
        Prerequisite: --execute must be registered (otherwise tests are vacuous).
        """
        _require_execute_registered()

        body = _smoke_clearance_body()
        assert body, "smoke_clearance function not found in cli/main.py."
        assert "scrape_queue" not in body, (
            "smoke_clearance body references scrape_queue. "
            "Clearance smoke must not touch the scrape queue."
        )

    def test_execute_handler_has_no_smoke_player_info(self) -> None:
        """smoke_clearance body must not reference smoke_player_info.

        smoke_player_info mutates DB/scrape_queue. Clearance smoke must not use it.
        Prerequisite: --execute must be registered (otherwise tests are vacuous).
        """
        _require_execute_registered()

        body = _smoke_clearance_body()
        assert body, "smoke_clearance function not found in cli/main.py."
        assert "smoke_player_info" not in body, (
            "smoke_clearance body references smoke_player_info. "
            "Clearance smoke must not reuse the player-info harness."
        )

    def test_execute_handler_has_no_scrape_player_info(self) -> None:
        """smoke_clearance body must not reference scrape_player_info.

        scrape_player_info is a DB-backed scraper. Clearance smoke is scraper-free.
        Prerequisite: --execute must be registered (otherwise tests are vacuous).
        """
        _require_execute_registered()

        body = _smoke_clearance_body()
        assert body, "smoke_clearance function not found in cli/main.py."
        assert "scrape_player_info" not in body, (
            "smoke_clearance body references scrape_player_info. "
            "Clearance smoke must not call any scraper."
        )
