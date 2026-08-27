# cli/smoke_clearance_real.py
"""Real clearance smoke harness — interfaces, gate model, and orchestrator.

No real browser, network, DB, or Docker. All external interactions are injectable.
"""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

# ---------------------------------------------------------------------------
# Provider protocols (contracts only — no real implementations)
# ---------------------------------------------------------------------------


class TargetProvider(Protocol):
    def is_ready(self) -> bool: ...
    def source_class(self) -> str: ...  # label only, never raw value


class BrowserParameterProvider(Protocol):
    def is_ready(self) -> bool: ...
    def source_class(self) -> str: ...  # label only
    def validate_against_allowlist(self, allowlist: frozenset[str]) -> bool: ...


class TokenProvider(Protocol):
    def is_ready(self) -> bool: ...
    def source_class(self) -> str: ...  # label only, never raw value


# ---------------------------------------------------------------------------
# Gate seam interfaces
# ---------------------------------------------------------------------------


class CICheckResult(enum.Enum):
    ALL_PASS = "ALL_PASS"
    BLOCKED = "BLOCKED"


class CICheckProvider(Protocol):
    def check_once(self) -> CICheckResult: ...  # executes exactly once, no retry


class ValidationResult(enum.Enum):
    VALID = "VALID"
    BLOCKED = "BLOCKED"


class TargetValidator(Protocol):
    def validate(
        self, target_class: str
    ) -> ValidationResult: ...  # never prints target value


@dataclass
class ClearanceResult:
    obtained: bool
    expires_at: datetime | None
    clearance_class: str  # label only, never raw value


class WorkServerLifecycle(Protocol):
    def startup(self, timeout_s: int) -> None: ...
    def health_check(self) -> bool: ...
    def auth_failure_probe(self) -> int: ...  # HTTP status of garbage-token probe
    def shutdown(self) -> None: ...


class BrowserLauncher(Protocol):

    def start(self) -> bool: ...

    def wait_cdp_ready(
        self, timeout_s: int
    ) -> tuple[bool, int]: ...  # (ready, elapsed_s)

    def stop(self) -> None:
        """Stop the browser engine. Safe to call regardless of started state."""
        ...


class ClearanceObserver(Protocol):
    def observe(self, timeout_s: int) -> ClearanceResult: ...


class ClearancePostClient(Protocol):
    def post(
        self, clearance_class: str
    ) -> tuple[int, int]: ...  # (status_code, body_bytes)


# ---------------------------------------------------------------------------
# Gate result / report types
# ---------------------------------------------------------------------------


class GateStatus(enum.Enum):
    PASS = "PASS"
    BLOCKED = "BLOCKED"
    FAIL = "FAIL"


class HarnessStatus(enum.Enum):
    PASS = "PASS"
    BLOCKED = "BLOCKED"
    FAIL = "FAIL"


@dataclass
class HarnessReport:
    status: HarnessStatus
    gate_results: dict[str, GateStatus] = field(default_factory=dict)
    evidence: dict[str, object] = field(default_factory=dict)
    error_gate: str | None = None


# ---------------------------------------------------------------------------
# Redaction scanner (5 pattern classes)
# ---------------------------------------------------------------------------

_REDACTION_PATTERNS = [
    # HIGH-ENTROPY: 32+ hex chars
    re.compile(r"[0-9a-fA-F]{32,}"),
    # KEY-NAME: common secret key names
    re.compile(r"(?i)\b(password|secret|token|api_key|auth_key)\b\s*[=:]\s*\S+"),
    # URL-CREDENTIAL: userinfo in URL
    re.compile(r"[a-zA-Z][a-zA-Z0-9+\-.]*://[^/@\s]+:[^/@\s]+@"),
    # COOKIE-FORMAT: cf_clearance= pattern
    re.compile(r"(?i)cf_clearance\s*="),
    # DSN: postgresql:// or postgres://
    re.compile(r"(?i)postgres(?:ql)?://\S+"),
]


def scan_for_sensitive(value: str) -> bool:
    """Return True if value matches any redaction pattern (sensitive)."""
    for pattern in _REDACTION_PATTERNS:
        if pattern.search(value):
            return True
    return False


# ---------------------------------------------------------------------------
# Loopback assertion
# ---------------------------------------------------------------------------


def assert_loopback(host: str) -> bool:
    """Return True only if host is the string literal '127.0.0.1'.

    This is a string-equality check, not a DNS resolution.
    Accepts only the exact IPv4 loopback string — 'localhost' and '::1' are rejected.
    """
    return host == "127.0.0.1"


# ---------------------------------------------------------------------------
# expires_at guard
# ---------------------------------------------------------------------------

_MAX_CLEARANCE_WINDOW_S = 300  # 5 minutes


def check_expires_at(expires_at: datetime | None, now: datetime | None = None) -> bool:
    """Return True if now < expires_at <= now + 5min. Both bounds enforced."""
    if expires_at is None:
        return False
    if now is None:
        now = datetime.now(UTC)
    delta = (expires_at - now).total_seconds()
    return 0 < delta <= _MAX_CLEARANCE_WINDOW_S


# ---------------------------------------------------------------------------
# Token source class validation
# ---------------------------------------------------------------------------

_INVALID_SOURCE_CLASSES = frozenset({"", "test", "default", "placeholder"})


def validate_token_source_class(source_class: str) -> bool:
    """Return True if token source class is a valid non-placeholder label."""
    return source_class not in _INVALID_SOURCE_CLASSES


# ---------------------------------------------------------------------------
# RealClearanceHarness
# ---------------------------------------------------------------------------


@dataclass
class RealClearanceProviders:
    target: TargetProvider
    browser_params: BrowserParameterProvider
    token: TokenProvider


@dataclass
class RealClearanceSeams:
    ci_check: CICheckProvider
    work_server: WorkServerLifecycle
    target_validator: TargetValidator
    browser_launcher: BrowserLauncher
    clearance_observer: ClearanceObserver
    clearance_post: ClearancePostClient
    resolved_host: str = "127.0.0.1"  # injectable for loopback assertion
    browser_cdp_timeout_s: int = 30
    clearance_timeout_s: int = 120
    work_server_timeout_s: int = 30


class RealClearanceHarness:
    """Orchestrates the 15-gate real clearance smoke run.

    All external interactions are injected via providers and seams.
    Cleanup always runs in finally block regardless of gate outcome.
    """

    GATE_PROVIDER_READINESS = "provider_readiness"
    GATE_LOOPBACK = "loopback_assertion"
    GATE_CI_CHECK = "ci_check"
    GATE_TOKEN_SOURCE = "token_source_class"
    GATE_REDACTION_SELF_TEST = "redaction_self_test"
    GATE_WORK_SERVER_STARTUP = "work_server_startup"
    GATE_WORK_SERVER_HEALTH = "work_server_health"
    GATE_AUTH_FAILURE_PROBE = "auth_failure_probe"
    GATE_TARGET_VALIDATION = "target_validation"
    GATE_BROWSER_START = "browser_start"
    GATE_CDP_READY = "cdp_ready"
    GATE_CLEARANCE_OBSERVED = "clearance_observed"
    GATE_EXPIRES_AT = "expires_at_guard"
    GATE_POST_CLEARANCE = "post_clearance"
    GATE_FINAL_REDACTION = "final_redaction_scan"

    def _redact_str(self, value: str) -> str:
        """Redact sensitive patterns from a string before storing in evidence.

        Applies the same patterns as the final redaction scan gate.
        Returns '[REDACTED]' if any pattern matches, otherwise returns value[:200].
        """
        truncated = value[:200]
        if scan_for_sensitive(truncated):
            return "[REDACTED]"
        return truncated

    def run(
        self,
        providers: RealClearanceProviders,
        seams: RealClearanceSeams,
    ) -> HarnessReport:
        gate_results: dict[str, GateStatus] = {}
        evidence: dict[str, object] = {}
        error_gate: str | None = None

        try:
            # Gate 1: Provider readiness
            if not (
                providers.target.is_ready()
                and providers.browser_params.is_ready()
                and providers.token.is_ready()
            ):
                gate_results[self.GATE_PROVIDER_READINESS] = GateStatus.BLOCKED
                error_gate = self.GATE_PROVIDER_READINESS
                return HarnessReport(
                    status=HarnessStatus.BLOCKED,
                    gate_results=gate_results,
                    evidence=evidence,
                    error_gate=error_gate,
                )
            gate_results[self.GATE_PROVIDER_READINESS] = GateStatus.PASS

            # Gate 2: Loopback assertion
            if not assert_loopback(seams.resolved_host):
                gate_results[self.GATE_LOOPBACK] = GateStatus.BLOCKED
                error_gate = self.GATE_LOOPBACK
                return HarnessReport(
                    status=HarnessStatus.BLOCKED,
                    gate_results=gate_results,
                    evidence=evidence,
                    error_gate=error_gate,
                )
            gate_results[self.GATE_LOOPBACK] = GateStatus.PASS

            # Gate 3: CI check (exactly once, no retry)
            ci_result = seams.ci_check.check_once()
            if ci_result != CICheckResult.ALL_PASS:
                gate_results[self.GATE_CI_CHECK] = GateStatus.BLOCKED
                error_gate = self.GATE_CI_CHECK
                return HarnessReport(
                    status=HarnessStatus.BLOCKED,
                    gate_results=gate_results,
                    evidence={"ci_check_result": ci_result.value},
                    error_gate=error_gate,
                )
            gate_results[self.GATE_CI_CHECK] = GateStatus.PASS

            # Gate 4: Token source class validation
            token_src = providers.token.source_class()
            if not validate_token_source_class(token_src):
                gate_results[self.GATE_TOKEN_SOURCE] = GateStatus.BLOCKED
                error_gate = self.GATE_TOKEN_SOURCE
                return HarnessReport(
                    status=HarnessStatus.BLOCKED,
                    gate_results=gate_results,
                    evidence={"token_source_class": token_src},
                    error_gate=error_gate,
                )
            gate_results[self.GATE_TOKEN_SOURCE] = GateStatus.PASS
            evidence["token_source_class"] = token_src

            # Gate 5: Redaction self-test — 5 pattern classes, synthetic strings
            _SELF_TEST_INPUTS = [
                "aabbccddeeff00112233445566778899",  # HIGH-ENTROPY (32 hex)
                "password=supersecret",  # KEY-NAME
                "http://user:pass@example.com",  # URL-CREDENTIAL
                "cf_clearance=abc",  # COOKIE-FORMAT
                "postgresql://user:pw@localhost/db",  # DSN
            ]
            self_test_passed = all(scan_for_sensitive(s) for s in _SELF_TEST_INPUTS)
            if not self_test_passed:
                gate_results[self.GATE_REDACTION_SELF_TEST] = GateStatus.FAIL
                error_gate = self.GATE_REDACTION_SELF_TEST
                return HarnessReport(
                    status=HarnessStatus.FAIL,
                    gate_results=gate_results,
                    evidence=evidence,
                    error_gate=error_gate,
                )
            gate_results[self.GATE_REDACTION_SELF_TEST] = GateStatus.PASS

            # Gate 6: Target validation — before any network service starts
            target_src = providers.target.source_class()
            val_result = seams.target_validator.validate(target_src)
            evidence["target_validation_status"] = val_result.value
            if val_result != ValidationResult.VALID:
                gate_results[self.GATE_TARGET_VALIDATION] = GateStatus.BLOCKED
                error_gate = self.GATE_TARGET_VALIDATION
                return HarnessReport(
                    status=HarnessStatus.BLOCKED,
                    gate_results=gate_results,
                    evidence=evidence,
                    error_gate=error_gate,
                )
            gate_results[self.GATE_TARGET_VALIDATION] = GateStatus.PASS

            # Gate 7: work_server startup
            try:
                seams.work_server.startup(timeout_s=seams.work_server_timeout_s)
            except Exception as exc:
                gate_results[self.GATE_WORK_SERVER_STARTUP] = GateStatus.BLOCKED
                error_gate = self.GATE_WORK_SERVER_STARTUP
                # Exception diagnostics: _type + message pair convention.
                return HarnessReport(
                    status=HarnessStatus.BLOCKED,
                    gate_results=gate_results,
                    evidence={
                        **evidence,
                        "startup_error_type": type(exc).__name__,
                        "startup_error": self._redact_str(str(exc)),
                    },
                    error_gate=error_gate,
                )
            gate_results[self.GATE_WORK_SERVER_STARTUP] = GateStatus.PASS

            # Gate 8: work_server health check
            if not seams.work_server.health_check():
                gate_results[self.GATE_WORK_SERVER_HEALTH] = GateStatus.BLOCKED
                error_gate = self.GATE_WORK_SERVER_HEALTH
                return HarnessReport(
                    status=HarnessStatus.BLOCKED,
                    gate_results=gate_results,
                    evidence=evidence,
                    error_gate=error_gate,
                )
            gate_results[self.GATE_WORK_SERVER_HEALTH] = GateStatus.PASS

            # Gate 9: auth_failure_probe must return 401
            auth_probe_status = seams.work_server.auth_failure_probe()
            evidence["auth_probe_status"] = auth_probe_status
            if auth_probe_status != 401:
                gate_results[self.GATE_AUTH_FAILURE_PROBE] = GateStatus.BLOCKED
                error_gate = self.GATE_AUTH_FAILURE_PROBE
                return HarnessReport(
                    status=HarnessStatus.BLOCKED,
                    gate_results=gate_results,
                    evidence=evidence,
                    error_gate=error_gate,
                )
            gate_results[self.GATE_AUTH_FAILURE_PROBE] = GateStatus.PASS

            # Gate 10: Browser start
            if not seams.browser_launcher.start():
                gate_results[self.GATE_BROWSER_START] = GateStatus.BLOCKED
                error_gate = self.GATE_BROWSER_START
                return HarnessReport(
                    status=HarnessStatus.BLOCKED,
                    gate_results=gate_results,
                    evidence=evidence,
                    error_gate=error_gate,
                )
            gate_results[self.GATE_BROWSER_START] = GateStatus.PASS

            # Gate 11: CDP ready within timeout
            cdp_ready, cdp_elapsed = seams.browser_launcher.wait_cdp_ready(
                timeout_s=seams.browser_cdp_timeout_s
            )
            evidence["cdp_elapsed_s"] = cdp_elapsed
            if not cdp_ready:
                gate_results[self.GATE_CDP_READY] = GateStatus.BLOCKED
                error_gate = self.GATE_CDP_READY
                return HarnessReport(
                    status=HarnessStatus.BLOCKED,
                    gate_results=gate_results,
                    evidence=evidence,
                    error_gate=error_gate,
                )
            gate_results[self.GATE_CDP_READY] = GateStatus.PASS

            # Gate 12: Clearance observed within timeout
            try:
                clearance_result = seams.clearance_observer.observe(
                    timeout_s=seams.clearance_timeout_s
                )
            except PermissionError:
                gate_results[self.GATE_CLEARANCE_OBSERVED] = GateStatus.BLOCKED
                error_gate = self.GATE_CLEARANCE_OBSERVED
                return HarnessReport(
                    status=HarnessStatus.BLOCKED,
                    gate_results=gate_results,
                    evidence={
                        **evidence,
                        "clearance_getter_error_type": "PermissionError",
                        "clearance_getter_error": "auth_failure",
                    },
                    error_gate=error_gate,
                )
            except ConnectionError:
                gate_results[self.GATE_CLEARANCE_OBSERVED] = GateStatus.BLOCKED
                error_gate = self.GATE_CLEARANCE_OBSERVED
                return HarnessReport(
                    status=HarnessStatus.BLOCKED,
                    gate_results=gate_results,
                    evidence={
                        **evidence,
                        "clearance_getter_error_type": "ConnectionError",
                        "clearance_getter_error": "connection_failure",
                    },
                    error_gate=error_gate,
                )
            evidence["clearance_class"] = clearance_result.clearance_class
            evidence["clearance_obtained"] = clearance_result.obtained
            if not clearance_result.obtained:
                gate_results[self.GATE_CLEARANCE_OBSERVED] = GateStatus.BLOCKED
                error_gate = self.GATE_CLEARANCE_OBSERVED
                return HarnessReport(
                    status=HarnessStatus.BLOCKED,
                    gate_results=gate_results,
                    evidence=evidence,
                    error_gate=error_gate,
                )
            gate_results[self.GATE_CLEARANCE_OBSERVED] = GateStatus.PASS

            # Gate 13: expires_at guard (now < expires_at <= now + 5min)
            if not check_expires_at(clearance_result.expires_at):
                gate_results[self.GATE_EXPIRES_AT] = GateStatus.BLOCKED
                error_gate = self.GATE_EXPIRES_AT
                return HarnessReport(
                    status=HarnessStatus.BLOCKED,
                    gate_results=gate_results,
                    evidence=evidence,
                    error_gate=error_gate,
                )
            gate_results[self.GATE_EXPIRES_AT] = GateStatus.PASS

            # Gate 14: POST /api/clearance — expect 204 with zero body
            try:
                post_status, post_body_bytes = seams.clearance_post.post(
                    clearance_result.clearance_class
                )
            except ValueError as exc:
                gate_results[self.GATE_POST_CLEARANCE] = GateStatus.FAIL
                error_gate = self.GATE_POST_CLEARANCE
                # Exception diagnostics: _type + message pair convention.
                return HarnessReport(
                    status=HarnessStatus.FAIL,
                    gate_results=gate_results,
                    evidence={
                        **evidence,
                        "post_error_type": type(exc).__name__,
                        "post_error": self._redact_str(str(exc)),
                    },
                    error_gate=error_gate,
                )
            evidence["post_status_code"] = post_status
            evidence["post_body_bytes"] = post_body_bytes
            if post_status != 204:
                gate_results[self.GATE_POST_CLEARANCE] = GateStatus.BLOCKED
                error_gate = self.GATE_POST_CLEARANCE
                return HarnessReport(
                    status=HarnessStatus.BLOCKED,
                    gate_results=gate_results,
                    evidence=evidence,
                    error_gate=error_gate,
                )
            if post_body_bytes != 0:
                gate_results[self.GATE_POST_CLEARANCE] = GateStatus.BLOCKED
                error_gate = self.GATE_POST_CLEARANCE
                return HarnessReport(
                    status=HarnessStatus.BLOCKED,
                    gate_results=gate_results,
                    evidence=evidence,
                    error_gate=error_gate,
                )
            gate_results[self.GATE_POST_CLEARANCE] = GateStatus.PASS

            # Final redaction scan of all evidence fields
            for val in evidence.values():
                if isinstance(val, str) and scan_for_sensitive(val):
                    gate_results[self.GATE_FINAL_REDACTION] = GateStatus.FAIL
                    error_gate = self.GATE_FINAL_REDACTION
                    return HarnessReport(
                        status=HarnessStatus.FAIL,
                        gate_results=gate_results,
                        evidence={},  # sanitize output on redaction failure
                        error_gate=error_gate,
                    )
            gate_results[self.GATE_FINAL_REDACTION] = GateStatus.PASS

            return HarnessReport(
                status=HarnessStatus.PASS,
                gate_results=gate_results,
                evidence=evidence,
                error_gate=None,
            )

        finally:
            # Cleanup always runs — on PASS, BLOCKED, and FAIL paths
            try:
                seams.browser_launcher.stop()
            except Exception:
                pass
            try:
                seams.work_server.shutdown()
            except Exception:
                pass
