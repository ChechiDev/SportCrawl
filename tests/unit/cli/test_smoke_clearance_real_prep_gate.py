"""CP1.6h-RED — Contract tests for smoke-clearance --prepare-real gate.

Defines what smoke-clearance --prepare-real must look like when implemented.

Tests in TestPrepareRealOptionRegistration, TestPrepareRealExitBehavior,
TestPrepareRealOutputContent should FAIL until implementation is complete.
TestExistingModesPreserved should PASS before AND after.
TestPrepareRealSourceInspection validates safety invariants (may PASS before).

Contract summary:
- --prepare-real is mutually exclusive with --dry-run and --execute.
- --prepare-real enforces workers=1.
- --prepare-real exits 0 with a blocked/not-authorized planning summary.
- No browser/Chrome/Pydoll/CDP, no FBRef, no DB, no Docker, no work_server.
- Output is sanitized — no sensitive terms exposed.
"""

from __future__ import annotations

import re
from pathlib import Path

from typer.testing import CliRunner

from cli.main import app

runner = CliRunner()

_CLI_MAIN = Path(__file__).parents[3] / "cli" / "main.py"


def _src() -> str:
    return _CLI_MAIN.read_text(encoding="utf-8")


def _smoke_clearance_body() -> str:
    src = _src()
    m = re.search(
        r"(?:async\s+)?def\s+smoke_clearance\s*\([^)]*\)\s*->.*?"
        r"(?=\n(?:@app|def main|\Z))",
        src,
        re.DOTALL,
    )
    return m.group(0) if m else ""


# ---------------------------------------------------------------------------
# 1. Option registration (FAIL before, PASS after)
# ---------------------------------------------------------------------------


class TestPrepareRealOptionRegistration:
    def test_prepare_real_option_registered(self) -> None:
        """--prepare-real must be registered as a Click option on smoke-clearance.

        Expected RED: option is absent before implementation.
        """
        import typer.main as typer_main

        cli = typer_main.get_command(app)
        sub = getattr(cli, "commands", {}).get("smoke-clearance")
        assert sub is not None, (
            "smoke-clearance command not registered in the Typer app."
        )
        registered = any(
            "--prepare-real" in getattr(p, "opts", []) for p in sub.params
        )
        assert registered, (
            "--prepare-real option not registered on smoke-clearance. "
            "Implement --prepare-real in cli/main.py."
        )


# ---------------------------------------------------------------------------
# 2. Existing modes preserved (regression guards — PASS before AND after)
# ---------------------------------------------------------------------------


class TestExistingModesPreserved:
    def test_default_mode_is_dry_run(self) -> None:
        """smoke-clearance (no args) must still exit 0."""
        result = runner.invoke(app, ["smoke-clearance"])
        assert result.exit_code == 0, (
            f"smoke-clearance regressed: exit {result.exit_code}. "
            f"Output: {result.output}"
        )

    def test_dry_run_flag_preserved(self) -> None:
        """smoke-clearance --dry-run must still exit 0."""
        result = runner.invoke(app, ["smoke-clearance", "--dry-run"])
        assert result.exit_code == 0, (
            f"smoke-clearance --dry-run regressed: exit {result.exit_code}. "
            f"Output: {result.output}"
        )

    def test_execute_flag_preserved(self) -> None:
        """smoke-clearance --execute must still exit 0."""
        result = runner.invoke(app, ["smoke-clearance", "--execute"])
        assert result.exit_code == 0, (
            f"smoke-clearance --execute regressed: exit {result.exit_code}. "
            f"Output: {result.output}"
        )


# ---------------------------------------------------------------------------
# 3. --prepare-real exit behavior (FAIL before, PASS after)
# ---------------------------------------------------------------------------


class TestPrepareRealExitBehavior:
    def test_prepare_real_exits_zero(self) -> None:
        """smoke-clearance --prepare-real must exit 0."""
        result = runner.invoke(app, ["smoke-clearance", "--prepare-real"])
        assert result.exit_code == 0, (
            f"smoke-clearance --prepare-real exited {result.exit_code}. "
            f"Output: {result.output}"
        )

    def test_prepare_real_reports_blocked(self) -> None:
        """--prepare-real output must include 'blocked' or 'not authorized'."""
        result = runner.invoke(app, ["smoke-clearance", "--prepare-real"])
        output_lower = result.output.lower()
        assert "blocked" in output_lower or "not authorized" in output_lower, (
            "--prepare-real must report blocked/not authorized. "
            f"Got: {result.output!r}"
        )

    def test_prepare_real_workers_1_accepted(self) -> None:
        """--prepare-real --workers 1 must exit 0."""
        result = runner.invoke(
            app, ["smoke-clearance", "--prepare-real", "--workers", "1"]
        )
        assert result.exit_code == 0, (
            f"smoke-clearance --prepare-real --workers 1 failed: {result.output}"
        )


# ---------------------------------------------------------------------------
# 4. Conflict rejection (FAIL before for wrong reason, validate after)
# ---------------------------------------------------------------------------


class TestPrepareRealConflictRejection:
    def test_prepare_real_and_dry_run_rejected(self) -> None:
        """--prepare-real --dry-run must be rejected (exit != 0)."""
        result = runner.invoke(
            app, ["smoke-clearance", "--prepare-real", "--dry-run"]
        )
        assert result.exit_code != 0, (
            "--prepare-real and --dry-run are mutually exclusive but were accepted. "
            f"Output: {result.output}"
        )

    def test_prepare_real_and_execute_rejected(self) -> None:
        """--prepare-real --execute must be rejected (exit != 0)."""
        result = runner.invoke(
            app, ["smoke-clearance", "--prepare-real", "--execute"]
        )
        assert result.exit_code != 0, (
            "--prepare-real and --execute are mutually exclusive but were accepted. "
            f"Output: {result.output}"
        )

    def test_prepare_real_workers_2_rejected(self) -> None:
        """--prepare-real --workers 2 must be rejected (exit != 0)."""
        result = runner.invoke(
            app, ["smoke-clearance", "--prepare-real", "--workers", "2"]
        )
        assert result.exit_code != 0, (
            "--prepare-real with --workers 2 must be rejected. "
            f"Output: {result.output}"
        )


# ---------------------------------------------------------------------------
# 5. Output content (FAIL before since no --prepare-real output)
# ---------------------------------------------------------------------------


class TestPrepareRealOutputContent:
    def _invoke(self) -> str:
        result = runner.invoke(app, ["smoke-clearance", "--prepare-real"])
        return result.output

    def test_output_includes_prepare_real_term(self) -> None:
        """Output must include 'prepare-real' or 'prepare_real'."""
        out = self._invoke()
        assert "prepare-real" in out or "prepare_real" in out, (
            f"Output must include prepare-real term. Got: {out!r}"
        )

    def test_output_includes_blocked_term(self) -> None:
        """Output must include 'blocked'."""
        out = self._invoke()
        assert "blocked" in out.lower(), (
            f"Output must include 'blocked'. Got: {out!r}"
        )

    def test_output_includes_workers_1(self) -> None:
        """Output must reference workers and the value 1."""
        out = self._invoke()
        assert "workers" in out.lower() and "1" in out, (
            f"Output must include workers and 1. Got: {out!r}"
        )

    def test_output_includes_loopback(self) -> None:
        """Output must reference '127.0.0.1' or 'loopback'."""
        out = self._invoke()
        assert "127.0.0.1" in out or "loopback" in out.lower(), (
            f"Output must include loopback address. Got: {out!r}"
        )

    def test_output_includes_api_clearance(self) -> None:
        """Output must reference '/api/clearance'."""
        out = self._invoke()
        assert "/api/clearance" in out, (
            f"Output must include /api/clearance. Got: {out!r}"
        )

    def test_output_includes_expected_204(self) -> None:
        """Output must include '204'."""
        out = self._invoke()
        assert "204" in out, (
            f"Output must include 204 (expected response). Got: {out!r}"
        )

    def test_output_includes_chrome_storage_local(self) -> None:
        """Output must reference 'chrome.storage.local'."""
        out = self._invoke()
        assert "chrome.storage.local" in out, (
            f"Output must include chrome.storage.local. Got: {out!r}"
        )

    def test_output_includes_disable_task_polling(self) -> None:
        """Output must reference 'disable_task_polling'."""
        out = self._invoke()
        assert "disable_task_polling" in out, (
            f"Output must include disable_task_polling. Got: {out!r}"
        )

    def test_output_includes_temp_profile(self) -> None:
        """Output must reference 'temp profile' or 'temporary profile'."""
        out = self._invoke()
        out_lower = out.lower()
        assert "temp profile" in out_lower or "temporary profile" in out_lower, (
            f"Output must include temp/temporary profile. Got: {out!r}"
        )

    def test_output_includes_cleanup(self) -> None:
        """Output must reference 'cleanup'."""
        out = self._invoke()
        assert "cleanup" in out.lower(), (
            f"Output must include cleanup. Got: {out!r}"
        )

    def test_output_excludes_sensitive_terms(self) -> None:
        """--prepare-real output must not include sensitive terms."""
        result = runner.invoke(app, ["smoke-clearance", "--prepare-real"])
        out_lower = result.output.lower()
        _SENSITIVE = (
            "cf_clearance",
            "token",
            "cookie",
            "profile_path",
            "cdp",
            "raw_html",
            "dsn",
            "postgres_password",
            "db__password",
            "database_url",
            "authorization",
            "bearer",
            "websocket",
        )
        for term in _SENSITIVE:
            assert term not in out_lower, (
                f"Sensitive term '{term}' found in --prepare-real output. "
                "Sanitize all sensitive values before printing."
            )


# ---------------------------------------------------------------------------
# 6. Source inspection — handler body must not contain forbidden refs
# ---------------------------------------------------------------------------


def _prepare_real_branch() -> str:
    """Extract only the prepare_real branch from the handler body.

    Looks for the block starting with 'if prepare_real:' inside
    smoke_clearance. Returns the branch text for targeted inspection.
    Falls back to the full body if the branch is not yet present.
    """
    body = _smoke_clearance_body()
    m = re.search(r"if prepare_real:(.*?)(?=\n\s*(?:if |#|return|\Z))", body, re.DOTALL)
    return m.group(0) if m else body


class TestPrepareRealSourceInspection:
    """Static source inspection. No execution — safe guards for after impl.

    Checks that the prepare_real branch (or the whole handler if the branch
    is not yet present) does not introduce live-state imports or calls.
    """

    def test_no_pydoll_in_handler(self) -> None:
        """smoke_clearance body must not reference pydoll."""
        body = _smoke_clearance_body()
        assert body, "smoke_clearance not found in cli/main.py."
        assert "pydoll" not in body.lower(), (
            "smoke_clearance handler body references pydoll. "
            "No Pydoll/CDP must be used in the handler."
        )

    def test_no_fbref_in_handler(self) -> None:
        """smoke_clearance body must not reference fbref."""
        body = _smoke_clearance_body()
        assert body, "smoke_clearance not found in cli/main.py."
        assert "fbref" not in body.lower(), (
            "smoke_clearance handler body references fbref. "
            "No FBRef network calls in the handler."
        )

    def test_no_asyncpg_in_handler(self) -> None:
        """smoke_clearance body must not reference asyncpg."""
        body = _smoke_clearance_body()
        assert body, "smoke_clearance not found in cli/main.py."
        assert "asyncpg" not in body.lower(), (
            "smoke_clearance handler body references asyncpg. "
            "No DB connections in the handler."
        )

    def test_no_tasks_api_in_handler(self) -> None:
        """smoke_clearance body must not reference /api/tasks endpoints."""
        body = _smoke_clearance_body()
        assert body, "smoke_clearance not found in cli/main.py."
        assert "/api/tasks/next" not in body and "/api/tasks/" not in body, (
            "smoke_clearance handler body references /api/tasks endpoint. "
            "Task polling is forbidden in the clearance handler."
        )

    def test_no_scrape_queue_in_handler(self) -> None:
        """smoke_clearance body must not reference scrape_queue."""
        body = _smoke_clearance_body()
        assert body, "smoke_clearance not found in cli/main.py."
        assert "scrape_queue" not in body, (
            "smoke_clearance handler body references scrape_queue."
        )

    def test_no_player_info_exec_in_handler(self) -> None:
        """smoke_clearance body must not reference scrape_player_info."""
        body = _smoke_clearance_body()
        assert body, "smoke_clearance not found in cli/main.py."
        assert "scrape_player_info" not in body, (
            "smoke_clearance handler body references scrape_player_info."
        )

    def test_no_chrome_launch_in_handler(self) -> None:
        """prepare_real branch must not import or call chrome/launch.

        String literals in console.print are plan output, not live calls.
        Only flag import, from, or bare call-like lines.
        """
        branch = _prepare_real_branch()
        assert branch, "smoke_clearance not found in cli/main.py."
        _CALL_PREFIXES = ("import ", "from ", "await ", "asyncio.")
        for line in branch.splitlines():
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            if not any(stripped.startswith(p) for p in _CALL_PREFIXES):
                continue
            line_lower = stripped.lower()
            assert "chrome" not in line_lower and "launch" not in line_lower, (
                f"Import/call line in prepare_real branch references "
                f"'chrome' or 'launch': {line!r}"
            )

    def test_no_docker_in_handler(self) -> None:
        """prepare_real branch must not import or call docker.

        String literals in console.print are plan output, not live calls.
        Only flag import, from, or bare call-like lines.
        """
        branch = _prepare_real_branch()
        assert branch, "smoke_clearance not found in cli/main.py."
        _CALL_PREFIXES = ("import ", "from ", "await ", "asyncio.")
        for line in branch.splitlines():
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            if not any(stripped.startswith(p) for p in _CALL_PREFIXES):
                continue
            assert "docker" not in stripped.lower(), (
                f"Import/call line in prepare_real branch references "
                f"'docker': {line!r}"
            )
