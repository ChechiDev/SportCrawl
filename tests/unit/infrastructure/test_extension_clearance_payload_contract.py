"""CP1.6b-RED — Static contract test: Chrome extension vs /api/clearance backend.

Inspects extensions/sportcrawl-chrome/background.js source to verify
the extension clearance POST payload matches the backend contract defined by
_CLEARANCE_REQUIRED_KEYS in infrastructure/work_server/server.py.

Backend required fields:
    domain, profile_id, worker_id, observed_at, expires_at, clearance

Tests in this module are RED until CP1.6c aligns the extension payload.

Static source inspection only — no browser, no network, no secrets.
"""

from __future__ import annotations

import re
from pathlib import Path

_BG_PATH = (
    Path(__file__).parents[3] / "extensions" / "sportcrawl-chrome" / "background.js"
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _src() -> str:
    """Return background.js source. Cached for the test session."""
    return _BG_PATH.read_text(encoding="utf-8")


def _clearance_post_block(src: str) -> str:
    """Extract the fetch() block that posts to /api/clearance.

    Returns the substring from the clearance endpoint URL assignment up to
    the closing of that fetch call. Used to scope field-presence checks so
    they cannot accidentally match unrelated fetch blocks.
    """
    # Find the line that defines the /api/clearance URL, then take the next
    # 30 lines which cover the entire fetch + JSON.stringify block.
    lines = src.splitlines()
    start = None
    for i, line in enumerate(lines):
        if "/api/clearance" in line and "work_server_url" in line:
            start = i
            break
    if start is None:
        return ""
    return "\n".join(lines[start : start + 30])


# ---------------------------------------------------------------------------
# Structure tests — these pass even before CP1.6c
# ---------------------------------------------------------------------------


class TestExtensionClearanceStructure:
    """Structural assertions that hold regardless of payload shape."""

    def test_background_js_exists(self) -> None:
        """background.js must exist at the expected path."""
        assert _BG_PATH.exists(), f"background.js not found at {_BG_PATH}"

    def test_extension_posts_to_clearance_endpoint(self) -> None:
        """Extension must reference /api/clearance as the POST target."""
        src = _src()
        assert "/api/clearance" in src, (
            "Extension must POST to /api/clearance. "
            "Not found in background.js."
        )

    def test_payload_uses_json_stringify(self) -> None:
        """Extension must serialise the payload with JSON.stringify."""
        block = _clearance_post_block(_src())
        assert "JSON.stringify" in block, (
            "Clearance POST must use JSON.stringify to serialise the payload. "
            "Not found in the /api/clearance fetch block."
        )

    def test_request_includes_content_type_json(self) -> None:
        """Extension must set Content-Type: application/json on the clearance POST."""
        block = _clearance_post_block(_src())
        assert "application/json" in block, (
            "Clearance POST must include Content-Type: application/json. "
            "Not found in the /api/clearance fetch block."
        )

    def test_request_includes_auth_headers(self) -> None:
        """Extension must include auth headers (authHeaders()) on the clearance POST."""
        block = _clearance_post_block(_src())
        assert "authHeaders()" in block, (
            "Clearance POST must spread authHeaders() into request headers. "
            "Not found in the /api/clearance fetch block."
        )

    def test_extension_sends_domain_field(self) -> None:
        """Extension must include a 'domain' field in the clearance payload."""
        block = _clearance_post_block(_src())
        # 'domain:' is a valid JS object key
        assert re.search(r"\bdomain\s*:", block), (
            "Clearance payload must include 'domain' field. "
            "Not found in the /api/clearance fetch block."
        )


# ---------------------------------------------------------------------------
# Contract mismatch tests — these are RED until CP1.6c
# ---------------------------------------------------------------------------


class TestExtensionClearanceContractMismatch:
    """CP1.6b RED — These tests prove the current extension payload does NOT
    satisfy the backend /api/clearance contract.

    All tests in this class are expected to FAIL until CP1.6c updates
    background.js to send the correct 6-field payload.
    """

    def test_payload_uses_clearance_not_cf_clearance(self) -> None:
        """Payload must use the key 'clearance', not the legacy 'cf_clearance'.

        Backend _CLEARANCE_REQUIRED_KEYS contains 'clearance'.
        Backend strict allowlist rejects unknown field 'cf_clearance' → 422.
        """
        block = _clearance_post_block(_src())
        # 'cf_clearance:' must NOT appear as a payload key in this block.
        has_legacy_key = bool(re.search(r"\bcf_clearance\s*:", block))
        assert not has_legacy_key, (
            "Extension still uses legacy field 'cf_clearance' in the payload. "
            "Backend requires 'clearance'. This causes a 422 on every POST."
        )
        # AND the correct key 'clearance:' must be present (without 'cf_' prefix).
        # We check for clearance: that is NOT preceded by 'cf_' on the same token.
        has_correct_key = bool(re.search(r"(?<!cf_)\bclearance\s*:", block))
        assert has_correct_key, (
            "Extension does not send required field 'clearance' (no 'cf_' prefix). "
            "Backend contract requires 'clearance' as the cookie value key."
        )

    def test_payload_includes_profile_id(self) -> None:
        """Payload must include 'profile_id' (browser/Chrome profile identifier).

        Backend _CLEARANCE_REQUIRED_KEYS requires 'profile_id'.
        Current extension omits it → 422 (missing required field).
        """
        block = _clearance_post_block(_src())
        assert re.search(r"\bprofile_id\s*:", block), (
            "Extension does not send required field 'profile_id'. "
            "Backend contract requires it → current payload returns 422."
        )

    def test_payload_includes_worker_id(self) -> None:
        """Payload must include 'worker_id' (scraper worker identifier).

        Backend _CLEARANCE_REQUIRED_KEYS requires 'worker_id'.
        Current extension omits it → 422 (missing required field).
        """
        block = _clearance_post_block(_src())
        assert re.search(r"\bworker_id\s*:", block), (
            "Extension does not send required field 'worker_id'. "
            "Backend contract requires it → current payload returns 422."
        )

    def test_payload_includes_observed_at(self) -> None:
        """Payload must include 'observed_at' (ISO-8601 UTC timestamp of capture).

        Backend _CLEARANCE_REQUIRED_KEYS requires 'observed_at'.
        Current extension omits it → 422 (missing required field).
        """
        block = _clearance_post_block(_src())
        assert re.search(r"\bobserved_at\s*:", block), (
            "Extension does not send required field 'observed_at'. "
            "Backend contract requires it → current payload returns 422."
        )

    def test_payload_includes_expires_at(self) -> None:
        """Payload must include 'expires_at' (ISO-8601 UTC timestamp of cookie expiry).

        Backend _CLEARANCE_REQUIRED_KEYS requires 'expires_at'.
        Current extension omits it → 422 (missing required field).
        """
        block = _clearance_post_block(_src())
        assert re.search(r"\bexpires_at\s*:", block), (
            "Extension does not send required field 'expires_at'. "
            "Backend contract requires it → current payload returns 422."
        )
