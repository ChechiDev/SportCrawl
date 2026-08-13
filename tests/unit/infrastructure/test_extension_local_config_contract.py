"""CP1.6f.1-RED — Static contract: extension token/config must be local-only.

Inspects extensions/sportcrawl-chrome/background.js and manifest.json to
verify that runtime configuration — specifically work_server_token — is read
from chrome.storage.local (device-local) and NOT from chrome.storage.sync
(cross-device synced).

Real smoke (CP1.6f) is blocked until these tests are GREEN.

Static source inspection only — no browser, no network, no secrets.
"""

from __future__ import annotations

import re
from pathlib import Path

_BG = Path(__file__).parents[3] / "extensions" / "sportcrawl-chrome" / "background.js"
_MANIFEST = (
    Path(__file__).parents[3] / "extensions" / "sportcrawl-chrome" / "manifest.json"
)

_RUNTIME_KEYS = ("work_server_url", "work_server_token", "profile_id", "worker_id")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _src() -> str:
    return _BG.read_text(encoding="utf-8")


def _manifest() -> str:
    return _MANIFEST.read_text(encoding="utf-8")


def _sync_get_block(src: str) -> str:
    """Return the chrome.storage.sync.get call block, if any."""
    m = re.search(r"chrome\.storage\.sync\.get\s*\(.*?\)", src, re.DOTALL)
    return m.group(0) if m else ""


def _local_get_block(src: str) -> str:
    """Return the chrome.storage.local.get call block used for runtime config."""
    # Find the call that contains work_server_token to scope correctly.
    m = re.search(
        r"chrome\.storage\.local\.get\s*\([^)]*work_server_token[^)]*\)",
        src,
        re.DOTALL,
    )
    return m.group(0) if m else ""


# ---------------------------------------------------------------------------
# Manifest tests — these are expected to pass already
# ---------------------------------------------------------------------------


class TestExtensionManifest:
    """Structural manifest assertions."""

    def test_manifest_exists(self) -> None:
        assert _MANIFEST.exists(), f"manifest.json not found at {_MANIFEST}"

    def test_storage_permission_present(self) -> None:
        """manifest.json must declare 'storage' permission."""
        manifest = _manifest()
        assert '"storage"' in manifest, (
            "manifest.json must include \"storage\" in permissions array. "
            "Required for chrome.storage API access."
        )

    def test_no_tabs_permission(self) -> None:
        """manifest.json must not request 'tabs' — not needed and too broad."""
        manifest = _manifest()
        assert '"tabs"' not in manifest, (
            "manifest.json must not request 'tabs' permission — not needed "
            "for clearance delivery and unnecessarily broad."
        )


# ---------------------------------------------------------------------------
# Token storage tests — RED until CP1.6f.2
# ---------------------------------------------------------------------------


class TestExtensionTokenStorage:
    """CP1.6f.1 RED — Token must be read from chrome.storage.local, not .sync.

    All tests in this class are expected to FAIL until CP1.6f.2 moves
    work_server_token (and all runtime config) from chrome.storage.sync
    to chrome.storage.local.
    """

    def test_token_read_from_local_not_sync(self) -> None:
        """work_server_token must be fetched via chrome.storage.local.get, not .sync.

        chrome.storage.sync propagates across signed-in Chrome profiles and
        devices. A smoke token in .sync can reach unintended machines.
        chrome.storage.local is device-local only.
        """
        src = _src()
        local_block = _local_get_block(src)
        assert local_block, (
            "Extension does not call chrome.storage.local.get with "
            "work_server_token. Token must be stored/read from .local for "
            "smoke safety."
        )

    def test_token_not_in_sync_get(self) -> None:
        """work_server_token must NOT appear inside chrome.storage.sync.get.

        Currently this fails because loadConfig() reads all config — including
        work_server_token — from chrome.storage.sync.
        """
        src = _src()
        sync_block = _sync_get_block(src)
        assert "work_server_token" not in sync_block, (
            "work_server_token is still read from chrome.storage.sync. "
            "This propagates the token across devices. "
            "Move to chrome.storage.local before CP1.6f real smoke."
        )

    def test_work_server_url_read_from_local(self) -> None:
        """work_server_url must also be in chrome.storage.local.get.

        For smoke safety all runtime config should be co-located in .local
        to prevent accidental cross-device exposure.
        """
        src = _src()
        local_block = _local_get_block(src)
        assert "work_server_url" in local_block, (
            "work_server_url is not present in chrome.storage.local.get. "
            "All runtime smoke config must be in .local."
        )

    def test_profile_id_read_from_local(self) -> None:
        """profile_id must appear in chrome.storage.local.get, not only .sync."""
        src = _src()
        local_block = _local_get_block(src)
        assert "profile_id" in local_block, (
            "profile_id is not present in chrome.storage.local.get. "
            "Runtime smoke config must be in .local."
        )

    def test_worker_id_read_from_local(self) -> None:
        """worker_id must appear in chrome.storage.local.get, not only .sync."""
        src = _src()
        local_block = _local_get_block(src)
        assert "worker_id" in local_block, (
            "worker_id is not present in chrome.storage.local.get. "
            "Runtime smoke config must be in .local."
        )

    def test_runtime_config_not_spread_across_sync_and_local(self) -> None:
        """Runtime config keys must appear in .local.get, not split across storages.

        Splitting config between .sync and .local creates ambiguity about
        which storage is authoritative and risks partial exposure.
        """
        src = _src()
        sync_block = _sync_get_block(src)
        # None of the runtime keys should appear in the .sync.get block.
        keys_in_sync = [k for k in _RUNTIME_KEYS if k in sync_block]
        assert not keys_in_sync, (
            f"Runtime config keys still read from chrome.storage.sync: "
            f"{keys_in_sync}. All must move to chrome.storage.local."
        )


# ---------------------------------------------------------------------------
# Token logging tests — expected to pass already (no token in logs today)
# but codified here so regressions are caught
# ---------------------------------------------------------------------------


class TestExtensionTokenNotLogged:
    """Token and auth values must never appear in console output.

    These tests are expected to pass in the current implementation.
    They are codified here to prevent regression during CP1.6f.2.
    """

    def test_token_value_not_in_console_log(self) -> None:
        """console.log must not include token variable values."""
        src = _src()
        # Look for console.log/warn/error calls that concatenate or reference
        # _config.work_server_token by name in a log statement.
        matches = re.findall(
            r'console\.\w+\s*\([^)]*work_server_token[^)]*\)',
            src,
        )
        assert not matches, (
            f"Found console output referencing work_server_token: {matches!r}. "
            "Token values must never be logged."
        )

    def test_authorization_header_not_logged(self) -> None:
        """The Authorization header value must not be passed to console output."""
        src = _src()
        # Check no console call stringifies authHeaders() output or logs Authorization
        matches = re.findall(
            r'console\.\w+\s*\([^)]*[Aa]uthorization[^)]*\)',
            src,
        )
        assert not matches, (
            f"Found console output referencing Authorization header: {matches!r}. "
            "Auth header values must never be logged."
        )

    def test_auth_headers_function_not_logged(self) -> None:
        """authHeaders() return value must not be passed to a console call."""
        src = _src()
        matches = re.findall(
            r'console\.\w+\s*\([^)]*authHeaders\(\)[^)]*\)',
            src,
        )
        assert not matches, (
            f"Found console output calling authHeaders(): {matches!r}. "
            "Auth header values must never be logged."
        )

    def test_missing_config_logs_only_generic_message(self) -> None:
        """When token/URL is not configured, warning must not include config values.

        Confirms the existing guard path logs a generic message only.
        """
        src = _src()
        # The guard block should contain a warn but must not embed work_server_token
        guard_match = re.search(
            r'if\s*\(!_config\.work_server_url[^}]+console\.\w+\s*\([^)]+\)',
            src,
            re.DOTALL,
        )
        if guard_match:
            guard_text = guard_match.group(0)
            assert "work_server_token" not in guard_text, (
                "Missing-config guard log includes work_server_token reference. "
                "Only generic non-sensitive messages are permitted."
            )
