from __future__ import annotations

import os

from cli.smoke_clearance_real import ValidationResult

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


class EnvTokenProvider:
    """Reads bearer token from SCRAPING__WORK_SERVER_TOKEN env var."""

    _SOURCE_CLASS = "env:SCRAPING__WORK_SERVER_TOKEN"

    def is_ready(self) -> bool:
        return bool(os.environ.get("SCRAPING__WORK_SERVER_TOKEN", "").strip())

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


class LabelTargetValidator:
    """Validates target source-class labels against known-safe set."""

    def validate(self, target_class: str) -> ValidationResult:
        if target_class in _VALID_TARGET_SOURCE_CLASSES:
            return ValidationResult.VALID
        return ValidationResult.BLOCKED
