"""CP1.6f.3-RED — Static contract: extension must support disable_task_polling.

Inspects extensions/sportcrawl-chrome/background.js to prove the extension
does not yet have a clearance-only smoke mode that disables task polling.

Real smoke (CP1.6f) requires that /api/tasks/next polling and alarm creation
can be disabled while /api/clearance delivery remains active.

Static source inspection only — no browser, no network, no secrets.
"""

from __future__ import annotations

import re
from pathlib import Path

_BG = Path(__file__).parents[3] / "extensions" / "sportcrawl-chrome" / "background.js"

_FLAG = "disable_task_polling"


def _src() -> str:
    return _BG.read_text(encoding="utf-8")


def _function_body(src: str, fn_name: str) -> str:
    """Extract the body of a named JS function (non-nested, first match)."""
    # Match: async? function <name>(...) { ... }
    # Captures balanced braces up to the first top-level closing brace.
    pattern = rf"(?:async\s+)?function\s+{re.escape(fn_name)}\s*\([^)]*\)\s*\{{"
    m = re.search(pattern, src)
    if not m:
        return ""
    start = m.end() - 1  # position of opening {
    depth = 0
    for i in range(start, len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[start : i + 1]
    return ""


# ---------------------------------------------------------------------------
# 1. disable_task_polling must be loaded from chrome.storage.local
# ---------------------------------------------------------------------------


class TestDisableTaskPollingConfig:
    """CP1.6f.3 RED — disable_task_polling must be declared in local config."""

    def test_disable_task_polling_config_is_loaded_from_local_storage(self) -> None:
        """chrome.storage.local.get must include disable_task_polling (default false).

        This allows clearance-only smoke to set disable_task_polling=true in
        local storage and suppress /api/tasks/next polling without modifying
        extension code.
        """
        src = _src()
        # Find the .local.get call that loads runtime config
        local_get = re.search(
            r"chrome\.storage\.local\.get\s*\(\s*\{[^}]*\}\s*,",
            src,
            re.DOTALL,
        )
        assert local_get, (
            "Could not find chrome.storage.local.get with an object of defaults. "
            "loadConfig must read runtime config from .local."
        )
        block = local_get.group(0)
        assert _FLAG in block, (
            f"'{_FLAG}' is not present in chrome.storage.local.get defaults. "
            "Smoke mode requires this flag to suppress task polling."
        )


# ---------------------------------------------------------------------------
# 2. pollNextTask must check the flag before fetching /api/tasks/next
# ---------------------------------------------------------------------------


class TestPollNextTaskGuard:
    """CP1.6f.3 RED — pollNextTask must be guarded by disable_task_polling."""

    def test_poll_next_task_has_disable_task_polling_guard_before_tasks_next_fetch(
        self,
    ) -> None:
        """pollNextTask() must check _config.disable_task_polling before
        issuing the GET /api/tasks/next fetch.

        Current state: no such guard exists. The function polls unconditionally
        whenever configReady is true.
        """
        src = _src()
        body = _function_body(src, "pollNextTask")
        assert body, "pollNextTask function not found in background.js."

        # Guard must appear before the /api/tasks/next fetch.
        guard_pos = body.find(_FLAG)
        tasks_pos = body.find("/api/tasks/next")

        assert guard_pos != -1, (
            f"pollNextTask does not reference '{_FLAG}'. "
            "The function must check this flag before fetching /api/tasks/next."
        )
        assert tasks_pos != -1, (
            "/api/tasks/next not found inside pollNextTask — unexpected structure."
        )
        assert guard_pos < tasks_pos, (
            f"'{_FLAG}' guard appears AFTER /api/tasks/next fetch in pollNextTask. "
            "Guard must precede the fetch."
        )

    def test_poll_skips_tasks_fetch_when_polling_disabled(self) -> None:
        """When disable_task_polling is set, pollNextTask must return early.

        There must be an early-return or similar skip path triggered by the flag
        before the /api/tasks/next fetch is reached.
        """
        src = _src()
        body = _function_body(src, "pollNextTask")
        assert body, "pollNextTask function not found."

        # Look for a pattern like: if (_config.disable_task_polling) return;
        # or if (disable_task_polling) ...
        early_return = re.search(
            rf"{_FLAG}[^;]*[;\n].*?return",
            body,
            re.DOTALL,
        )
        assert early_return, (
            f"pollNextTask has no early-return path guarded by '{_FLAG}'. "
            "Smoke mode requires unconditional return when polling is disabled."
        )


# ---------------------------------------------------------------------------
# 3. startAlarmIfNeeded must clear alarm when polling is disabled
# ---------------------------------------------------------------------------


class TestAlarmGuard:
    """CP1.6f.3 RED — startAlarmIfNeeded must clear alarm when polling disabled."""

    def test_start_alarm_clears_alarm_when_task_polling_disabled(self) -> None:
        """startAlarmIfNeeded must check disable_task_polling.

        When disabled, the function must clear ALARM_NAME (not create it) and
        return without scheduling a new alarm. This prevents spurious /api/tasks/next
        polls from firing during clearance-only smoke.
        """
        src = _src()
        body = _function_body(src, "startAlarmIfNeeded")
        assert body, "startAlarmIfNeeded function not found in background.js."

        assert _FLAG in body, (
            f"startAlarmIfNeeded does not reference '{_FLAG}'. "
            "Must check the flag and clear ALARM_NAME when disabled."
        )
        assert "chrome.alarms.clear" in body, (
            "startAlarmIfNeeded must call chrome.alarms.clear(ALARM_NAME) "
            "when disable_task_polling is true."
        )

    def test_alarm_not_created_when_polling_disabled(self) -> None:
        """When disable_task_polling is true, alarm creation must be skipped.

        The chrome.alarms.create call must not be reachable when the flag is set.
        """
        src = _src()
        body = _function_body(src, "startAlarmIfNeeded")
        assert body, "startAlarmIfNeeded function not found."

        flag_pos = body.find(_FLAG)
        create_pos = body.find("chrome.alarms.create")

        assert flag_pos != -1, (
            f"'{_FLAG}' not referenced in startAlarmIfNeeded."
        )
        # The clear call must appear before or at the flag branch, and the
        # create call must only be reachable in the non-disabled branch.
        # Simplest static proof: flag appears before alarm create.
        assert create_pos == -1 or flag_pos < create_pos, (
            f"'{_FLAG}' guard must appear before chrome.alarms.create in "
            "startAlarmIfNeeded to prevent alarm creation when disabled."
        )


# ---------------------------------------------------------------------------
# 4. Install/startup paths must rely on guarded alarm setup
# ---------------------------------------------------------------------------


class TestInstallStartupAlarmPaths:
    """CP1.6f.3 RED — install/startup must use the guarded startAlarmIfNeeded."""

    def test_install_startup_call_start_alarm_which_contains_disable_guard(
        self,
    ) -> None:
        """onInstalled and onStartup call startAlarmIfNeeded, which must contain
        the disable_task_polling guard.

        If startAlarmIfNeeded has no guard (current state), install/startup
        paths bypass smoke-mode isolation.
        """
        src = _src()
        # Confirm install/startup delegate to startAlarmIfNeeded (structural check).
        assert "startAlarmIfNeeded" in src, (
            "startAlarmIfNeeded not referenced in background.js — unexpected structure."
        )
        # The guard in startAlarmIfNeeded is the single point of truth;
        # this test delegates to the alarm-guard tests above but adds an
        # explicit assertion that the function called by install/startup
        # is the guarded one.
        body = _function_body(src, "startAlarmIfNeeded")
        assert body, "startAlarmIfNeeded function not found."
        assert _FLAG in body, (
            f"startAlarmIfNeeded (called by onInstalled/onStartup) does not "
            f"contain '{_FLAG}' guard. Install/startup paths will bypass "
            "smoke-mode isolation."
        )


# ---------------------------------------------------------------------------
# 5. /api/clearance must remain active regardless of disable_task_polling
# ---------------------------------------------------------------------------


class TestClearancePathUnaffected:
    """Regression guard — clearance delivery must not be gated by task-polling flag."""

    def test_clearance_post_path_not_gated_by_disable_task_polling(self) -> None:
        """/api/clearance fetch must not be guarded by disable_task_polling.

        Smoke mode disables task polling only; clearance delivery must remain
        active. This test passes today and serves as a regression guard for
        future CP1.6f.4 implementation.
        """
        src = _src()
        # Find the fetch block targeting /api/clearance
        clearance_block_m = re.search(
            r"const url = `[^`]*/api/clearance`.*?fetch\(url",
            src,
            re.DOTALL,
        )
        assert clearance_block_m, (
            "/api/clearance fetch block not found in background.js."
        )
        block = clearance_block_m.group(0)
        assert _FLAG not in block, (
            f"'/api/clearance' fetch block references '{_FLAG}'. "
            "Clearance delivery must NOT be gated by the task-polling disable flag."
        )


# ---------------------------------------------------------------------------
# 6. Task endpoint fetches must be isolated inside guarded functions
# ---------------------------------------------------------------------------


class TestTaskEndpointIsolation:
    """CP1.6f.3 RED — task endpoint fetches reachable only through guarded path."""

    def test_tasks_next_endpoint_only_in_poll_next_task(self) -> None:
        """/api/tasks/next must appear only inside pollNextTask.

        No other code path should fetch /api/tasks/next directly, ensuring
        the single disable guard in pollNextTask is sufficient.
        """
        src = _src()
        occurrences = [m.start() for m in re.finditer(r"/api/tasks/next", src)]
        assert occurrences, "/api/tasks/next not found in background.js."

        poll_body = _function_body(src, "pollNextTask")
        poll_start = src.find(poll_body) if poll_body else -1

        for pos in occurrences:
            in_poll = (
                poll_start != -1 and poll_start <= pos <= poll_start + len(poll_body)
            )
            assert in_poll, (
                f"/api/tasks/next found outside pollNextTask at position {pos}. "
                "Must be isolated inside the guarded function."
            )

    def test_tasks_result_endpoint_only_in_post_task_result(self) -> None:
        """/api/tasks/${{id}}/result must appear only inside postTaskResult.

        postTaskResult is only reachable through pollNextTask → executeFetchTask,
        which is behind the disable_task_polling guard.
        """
        src = _src()
        # Template literal: /api/tasks/${taskId}/result
        occurrences = [m.start() for m in re.finditer(r"/api/tasks/\$\{", src)]
        assert occurrences, "/api/tasks/${...}/result not found in background.js."

        result_body = _function_body(src, "postTaskResult")
        result_start = src.find(result_body) if result_body else -1

        for pos in occurrences:
            in_result = (
                result_start != -1
                and result_start <= pos <= result_start + len(result_body)
            )
            assert in_result, (
                f"/api/tasks/${{id}} found outside postTaskResult at position {pos}. "
                "Must be isolated inside the guarded function chain."
            )

    def test_poll_next_task_guard_chains_to_task_fetch(self) -> None:
        """pollNextTask disable guard must appear before executeFetchTask call.

        If the guard is present but after executeFetchTask is called, tasks
        would execute before smoke mode can stop them.
        """
        src = _src()
        body = _function_body(src, "pollNextTask")
        assert body, "pollNextTask not found."

        guard_pos = body.find(_FLAG)
        exec_pos = body.find("executeFetchTask")

        assert guard_pos != -1, (
            f"'{_FLAG}' guard not found in pollNextTask — required for smoke isolation."
        )
        assert exec_pos != -1, (
            "executeFetchTask not called from pollNextTask — unexpected structure."
        )
        assert guard_pos < exec_pos, (
            f"'{_FLAG}' guard appears after executeFetchTask in pollNextTask. "
            "Guard must precede all task execution paths."
        )
