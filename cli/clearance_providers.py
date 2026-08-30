from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable

from cli.smoke_clearance_real import CICheckResult, ValidationResult

_VALID_TARGET_SOURCE_CLASSES: frozenset[str] = frozenset(
    {"env:SCRAPING__WORK_SERVER_HOST"}
)


class EnvTargetProvider:
    """Reads target host from SCRAPING__WORK_SERVER_HOST env var."""

    _SOURCE_CLASS = "env:SCRAPING__WORK_SERVER_HOST"

    def is_ready(self) -> bool:
        return bool(os.environ.get("SCRAPING__WORK_SERVER_HOST", "").strip())

    def source_class(self) -> str:
        return self._SOURCE_CLASS


_TOKEN_ENV_KEY = "SCRAPING__WORK_SERVER_TOKEN"


def _default_token_reader() -> str:
    """Read token from os.environ first, then fall back to .env on disk.

    This mirrors the resolution order pydantic-settings uses, without requiring
    a full Settings() instantiation (which needs all required fields to be set).
    """
    val = os.environ.get(_TOKEN_ENV_KEY, "")
    if val:
        return val.strip()
    try:
        from dotenv import dotenv_values

        dotenv_val = dotenv_values(".env").get(_TOKEN_ENV_KEY, "")
        return (dotenv_val or "").strip()
    except (ImportError, OSError):
        return ""


def _env_only_token_reader() -> str:
    """Read token from os.environ only (no .env file). Safe for use with monkeypatch."""
    return os.environ.get(_TOKEN_ENV_KEY, "").strip()


class EnvTokenProvider:
    """Reads bearer token via Settings (resolves both os.environ and .env)."""

    _SOURCE_CLASS = "env:SCRAPING__WORK_SERVER_TOKEN"

    def __init__(
        self,
        token_reader: Callable[[], str] | None = None,
    ) -> None:
        self._token_reader = (
            token_reader if token_reader is not None else _default_token_reader
        )

    def is_ready(self) -> bool:
        return bool(self._token_reader().strip())

    def source_class(self) -> str:
        return self._SOURCE_CLASS


class EnvBrowserParameterProvider:
    """Reads Chrome profile path from SCRAPING__CHROME_PROFILE_DIR env var."""

    _SOURCE_CLASS = "env:SCRAPING__CHROME_PROFILE_DIR"

    def is_ready(self) -> bool:
        return bool(os.environ.get("SCRAPING__CHROME_PROFILE_DIR", "").strip())

    def source_class(self) -> str:
        return self._SOURCE_CLASS

    def validate_against_allowlist(self, allowlist: frozenset[str]) -> bool:
        return self._SOURCE_CLASS in allowlist


def _default_gh_runner(cmd: list[str]) -> tuple[int, str]:
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return (result.returncode, result.stdout)


class GhCICheckProvider:
    """Checks GitHub CI status via `gh run list`."""

    _GH_CMD = [
        "gh",
        "run",
        "list",
        "--json",
        "headBranch,status,conclusion,workflowName,createdAt",
        "--limit",
        "20",
    ]

    def __init__(
        self,
        runner: Callable[[list[str]], tuple[int, str]] = _default_gh_runner,
        workflow_name: str | None = None,
    ) -> None:
        self._runner = runner
        self._workflow_name = workflow_name

    def check_once(self) -> CICheckResult:
        returncode, stdout = self._runner(self._GH_CMD)
        if returncode != 0:
            return CICheckResult.BLOCKED
        try:
            runs: list[dict[str, str | None]] = json.loads(stdout)
        except (json.JSONDecodeError, ValueError):
            return CICheckResult.BLOCKED
        if self._workflow_name is not None:
            runs = [r for r in runs if r.get("workflowName") == self._workflow_name]
        runs.sort(key=lambda r: r.get("createdAt") or "", reverse=True)
        if not runs:
            return CICheckResult.BLOCKED
        latest = runs[0]
        if latest.get("status") != "completed":
            return CICheckResult.BLOCKED
        if latest.get("conclusion") == "success":
            return CICheckResult.ALL_PASS
        return CICheckResult.BLOCKED


class LabelTargetValidator:
    """Validates target source-class labels against known-safe set."""

    def validate(self, target_class: str) -> ValidationResult:
        if target_class in _VALID_TARGET_SOURCE_CLASSES:
            return ValidationResult.VALID
        return ValidationResult.BLOCKED
