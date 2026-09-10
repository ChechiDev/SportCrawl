"""Static analysis tests for background.js service-worker resilience patterns."""

import json
import re
import subprocess
from pathlib import Path

_BG = (
    Path(__file__).parents[3] / "extensions" / "sportcrawl-chrome" / "background.js"
).read_text()


def _get_listener_body() -> str:
    """Extract the cookie listener callback body using brace-depth traversal."""
    lines = _BG.splitlines()
    marker = "chrome.cookies.onChanged.addListener"
    start = next(
        (i for i, ln in enumerate(lines) if marker in ln),
        None,
    )
    assert start is not None, "chrome.cookies.onChanged.addListener not found"
    depth = 0
    body_lines: list[str] = []
    in_body = False
    for ln in lines[start:]:
        opens = ln.count("{")
        closes = ln.count("}")
        if not in_body and opens > 0:
            in_body = True
        depth += opens - closes
        body_lines.append(ln)
        if in_body and depth == 0:
            break
    return "\n".join(body_lines)


class TestDomainGeneralization:
    def test_no_fbref_hardcode_in_cookie_listener(self) -> None:
        listener_body = _get_listener_body()
        assert "fbref.com" not in listener_body, (
            '"fbref.com" must not appear in the cookie listener body'
        )

    def test_allowed_clearance_domain_variable_used_in_listener(self) -> None:
        listener_body = _get_listener_body()
        assert "_allowedClearanceDomain" in listener_body, (
            '"_allowedClearanceDomain" must appear in the cookie listener body'
        )

    def test_loadconfig_reads_allowed_clearance_domain(self) -> None:
        lines = _BG.splitlines()
        start = next(
            (i for i, ln in enumerate(lines) if "async function loadConfig()" in ln),
            None,
        )
        assert start is not None, "loadConfig() not found in background.js"
        depth = 0
        body_lines: list[str] = []
        for ln in lines[start:]:
            depth += ln.count("{") - ln.count("}")
            body_lines.append(ln)
            if depth == 0 and body_lines:
                break
        func_body = "\n".join(body_lines)
        assert "allowed_clearance_domain" in func_body, (
            '"allowed_clearance_domain" must be read inside loadConfig()'
        )

    def test_domain_matches_function_defined(self) -> None:
        assert "_domainMatches" in _BG, (
            '"_domainMatches" helper must be defined in background.js'
        )

    def test_domain_includes_not_used_in_listener(self) -> None:
        listener_body = _get_listener_body()
        assert "cookie.domain.includes" not in listener_body, (
            '"cookie.domain.includes" must not appear in the cookie listener body'
        )

    def _get_domain_matches_body(self) -> str:
        lines = _BG.splitlines()
        start = next(
            (i for i, ln in enumerate(lines) if "function _domainMatches" in ln),
            None,
        )
        assert start is not None, "_domainMatches function not found in background.js"
        depth = 0
        body_lines: list[str] = []
        for ln in lines[start:]:
            depth += ln.count("{") - ln.count("}")
            body_lines.append(ln)
            if depth == 0 and body_lines:
                break
        return "\n".join(body_lines)

    def test_domain_matches_rejects_substring_attack(self) -> None:
        body = self._get_domain_matches_body()
        assert "endsWith" in body, (
            "_domainMatches must use endsWith for boundary-safe suffix check"
        )

    def test_domain_matches_exact_match_pattern(self) -> None:
        body = self._get_domain_matches_body()
        assert "=== allowedDomain" in body, (
            "_domainMatches must include exact match arm: "
            "cookieDomain === allowedDomain"
        )

    def test_domain_matches_dot_prefix_pattern(self) -> None:
        body = self._get_domain_matches_body()
        has_dot_prefix = (
            ('=== "." + allowedDomain' in body)
            or ("=== '.' + allowedDomain" in body)
        )
        assert has_dot_prefix, (
            "_domainMatches must include dot-prefix arm: "
            'cookieDomain === "." + allowedDomain'
        )

    # ------------------------------------------------------------------
    # Behavioral contract tests — executed via node
    # ------------------------------------------------------------------

    def _eval_domain_matches(self, cookie_domain: str, allowed: str) -> bool:
        """Run _domainMatches from the real background.js body via node."""
        body = self._get_domain_matches_body()
        cd = json.dumps(cookie_domain)
        ad = json.dumps(allowed)
        script = f"{body}\nconsole.log(JSON.stringify(_domainMatches({cd}, {ad})));"
        result = subprocess.run(
            ["node", "-e", script],
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert result.returncode == 0, (
            f"node exited {result.returncode}: {result.stderr}"
        )
        return json.loads(result.stdout.strip())

    def test_behavioral_exact_match(self) -> None:
        assert self._eval_domain_matches("example.com", "example.com") is True

    def test_behavioral_dot_prefix(self) -> None:
        assert self._eval_domain_matches(".example.com", "example.com") is True

    def test_behavioral_subdomain(self) -> None:
        assert self._eval_domain_matches("sub.example.com", "example.com") is True

    def test_behavioral_boundary_attack_rejected(self) -> None:
        """notexample.com must NOT match example.com — substring-boundary safety."""
        assert self._eval_domain_matches("notexample.com", "example.com") is False

    def test_behavioral_empty_allowed_rejected(self) -> None:
        assert self._eval_domain_matches("anything.com", "") is False


class TestPostbackDiagnostics:
    # ------------------------------------------------------------------
    # Structure guards (minimal — prove the contract exists in the file)
    # ------------------------------------------------------------------

    def test_last_clearance_post_status_key_present(self) -> None:
        # Count chrome.storage.local.set calls that include last_clearance_post_status.
        # This catches write sites, not raw string occurrences (e.g. comments).
        write_sites = re.findall(
            r"chrome\.storage\.local\.set\([^)]*last_clearance_post_status",
            _BG,
            re.DOTALL,
        )
        assert len(write_sites) >= 3, (
            f"Expected at least 3 chrome.storage.local.set calls containing "
            f'"last_clearance_post_status" '
            f"(missing-domain, fetch success, fetch error); "
            f"found {len(write_sites)}"
        )

    def test_drop_reason_not_attempted_present(self) -> None:
        """CLEARANCE_DOMAIN_NOT_CONFIGURED must appear as drop_reason."""
        assert "CLEARANCE_DOMAIN_NOT_CONFIGURED" in _BG, (
            '"CLEARANCE_DOMAIN_NOT_CONFIGURED" literal must appear in background.js'
        )

    def test_clearance_domain_not_configured_in_early_return_block(self) -> None:
        """Not-attempted early-return block must contain drop_reason and the literal."""
        lines = _BG.splitlines()
        # Find the early return block: lines between "if (!_allowedClearanceDomain)"
        # and the first "return;" that follows it
        start_idx = next(
            (i for i, ln in enumerate(lines) if "if (!_allowedClearanceDomain)" in ln),
            None,
        )
        assert start_idx is not None, (
            '"if (!_allowedClearanceDomain)" block not found in background.js'
        )
        # Collect lines inside that if-block using brace depth
        depth = 0
        block_lines: list[str] = []
        in_block = False
        for ln in lines[start_idx:]:
            opens = ln.count("{")
            closes = ln.count("}")
            if not in_block and opens > 0:
                in_block = True
            depth += opens - closes
            block_lines.append(ln)
            if in_block and depth == 0:
                break
        block = "\n".join(block_lines)
        assert "CLEARANCE_DOMAIN_NOT_CONFIGURED" in block, (
            '"CLEARANCE_DOMAIN_NOT_CONFIGURED" must appear inside the '
            '"if (!_allowedClearanceDomain)" block'
        )
        assert "drop_reason" in block, (
            '"drop_reason" field must appear inside the not-attempted '
            "early-return block; got: " + block[:300]
        )

    def test_skip_reason_not_present(self) -> None:
        """skip_reason must be removed — schema now uses drop_reason / error_class."""
        assert "skip_reason" not in _BG, (
            '"skip_reason" must be removed from background.js; '
            "use drop_reason for not-attempted and error_class for network failures"
        )

    def test_error_class_field_present(self) -> None:
        """Attempted-failure schema must use error_class, not skip_reason."""
        assert "error_class" in _BG, (
            '"error_class" field must appear in background.js '
            "for the network-failure schema"
        )

    def test_storage_write_catch_fallback_present(self) -> None:
        assert "storage write failed" in _BG, (
            'diagnostic storage writes must have a .catch fallback emitting '
            '"storage write failed"'
        )

    def test_sw_termination_comment_present(self) -> None:
        assert "SW termination window" in _BG, (
            "SW termination window must be documented in background.js"
        )

    def test_sw_termination_comment_no_distinguishable_claim(self) -> None:
        """SW termination comment must not claim stale/missing is distinguishable."""
        assert "distinguishable" not in _BG, (
            '"distinguishable" must be removed from the SW termination comment — '
            "the mechanism is not defined and the claim is unsupported"
        )

    def test_sw_termination_comment_inconclusive_language(self) -> None:
        """The SW termination comment must use 'inconclusive' language."""
        assert "inconclusive" in _BG, (
            'SW termination comment must use "inconclusive" '
            "to describe missing/stale status"
        )

    def test_sync_throw_guard_covers_all_three_diagnostic_writes(self) -> None:
        """All 3 diagnostic storage.local.set calls must be inside a try block."""
        lines = _BG.splitlines()
        set_call_indices = [
            i for i, ln in enumerate(lines)
            if "chrome.storage.local.set" in ln
            and "last_clearance_post_status" in ln
        ]
        # Each set call may span multiple lines; also check lines ±5 for the set keyword
        # but we scan backwards up to 5 lines for a "try {" line
        missing = []
        for idx in set_call_indices:
            window_start = max(0, idx - 5)
            window = lines[window_start:idx + 1]
            if not any("try {" in ln for ln in window):
                missing.append(idx + 1)  # 1-based line number
        assert not missing, (
            f"chrome.storage.local.set calls at lines {missing} are not "
            "inside a try {{ }} block (searched 5 lines back)"
        )

    # ------------------------------------------------------------------
    # HTTP status classifier — extracted helper + behavioral tests
    # ------------------------------------------------------------------

    def _get_http_classifier_body(self) -> str:
        lines = _BG.splitlines()
        start = next(
            (i for i, ln in enumerate(lines) if "function _classifyHttpStatus" in ln),
            None,
        )
        assert start is not None, (
            "_classifyHttpStatus function not found in background.js"
        )
        depth = 0
        body_lines: list[str] = []
        for ln in lines[start:]:
            depth += ln.count("{") - ln.count("}")
            body_lines.append(ln)
            if depth == 0 and body_lines:
                break
        return "\n".join(body_lines)

    def _eval_http_classifier(self, status: int) -> str:
        body = self._get_http_classifier_body()
        script = f"{body}\nconsole.log(JSON.stringify(_classifyHttpStatus({status})));"
        result = subprocess.run(
            ["node", "-e", script],
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert result.returncode == 0, (
            f"node exited {result.returncode}: {result.stderr}"
        )
        return json.loads(result.stdout.strip())

    def test_http_classifier_200(self) -> None:
        assert self._eval_http_classifier(200) == "2xx"

    def test_http_classifier_301(self) -> None:
        assert self._eval_http_classifier(301) == "3xx"

    def test_http_classifier_404(self) -> None:
        assert self._eval_http_classifier(404) == "4xx"

    def test_http_classifier_503(self) -> None:
        assert self._eval_http_classifier(503) == "5xx"

    # ------------------------------------------------------------------
    # Behavioral classifier tests — execute real JS via node
    # ------------------------------------------------------------------

    def _get_classifier_body(self) -> str:
        lines = _BG.splitlines()
        start = next(
            (i for i, ln in enumerate(lines) if "function _classifyFetchError" in ln),
            None,
        )
        assert start is not None, (
            "_classifyFetchError function not found in background.js"
        )
        depth = 0
        body_lines: list[str] = []
        for ln in lines[start:]:
            depth += ln.count("{") - ln.count("}")
            body_lines.append(ln)
            if depth == 0 and body_lines:
                break
        return "\n".join(body_lines)

    def _eval_classifier(self, err_name: str | None) -> str:
        body = self._get_classifier_body()
        if err_name is None:
            err_js = "null"
        else:
            err_js = f'{{ name: {json.dumps(err_name)} }}'
        script = f"{body}\nconsole.log(JSON.stringify(_classifyFetchError({err_js})));"
        result = subprocess.run(
            ["node", "-e", script],
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert result.returncode == 0, (
            f"node exited {result.returncode}: {result.stderr}"
        )
        return json.loads(result.stdout.strip())

    def test_classifier_abort_error(self) -> None:
        assert self._eval_classifier("AbortError") == "aborted"

    def test_classifier_type_error(self) -> None:
        assert self._eval_classifier("TypeError") == "network_error"

    def test_classifier_unknown_error(self) -> None:
        assert self._eval_classifier("SomeOtherError") == "fetch_error"

    def test_classifier_null_error(self) -> None:
        assert self._eval_classifier(None) == "fetch_error"

    # ------------------------------------------------------------------
    # Safety guards
    # ------------------------------------------------------------------

    def test_no_cookie_value_in_listener(self) -> None:
        listener_body = _get_listener_body()
        lines = listener_body.splitlines()
        # Non-vacuous: assert last_clearance_post_status appears in listener
        found = any("last_clearance_post_status" in ln for ln in lines)
        assert found, '"last_clearance_post_status" not found in cookie listener body'
        # Safety: cookie.value must not appear within 10 lines of any write
        for i, line in enumerate(lines):
            if "last_clearance_post_status" in line:
                window_start = max(0, i - 10)
                window_end = min(len(lines), i + 10)
                window = lines[window_start:window_end]
                for wline in window:
                    assert "cookie.value" not in wline, (
                        f'"cookie.value" must not appear within 10 lines of '
                        f'"last_clearance_post_status" assignment (line {i})'
                    )

    def test_no_raw_token_in_listener(self) -> None:
        listener_body = _get_listener_body()
        assert "work_server_token" not in listener_body


class TestCookieListenerResilience:
    def test_cookie_listener_calls_load_config_before_readiness_check(self) -> None:
        listener_body = _get_listener_body()

        load_config_pos = listener_body.find("await loadConfig()")
        runtime_ready_pos = listener_body.find("_isRuntimeReady()")

        assert load_config_pos != -1, "loadConfig() call not found in cookie listener"
        assert runtime_ready_pos != -1, "_isRuntimeReady() check not found"
        assert load_config_pos < runtime_ready_pos, (
            f"loadConfig() (pos {load_config_pos}) must appear before "
            f"_isRuntimeReady() (pos {runtime_ready_pos}) in cookie listener"
        )

    def test_cookie_listener_is_async(self) -> None:
        listener_start = _BG.index("chrome.cookies.onChanged.addListener")
        before_body = _BG[listener_start : listener_start + 100]
        assert "async" in before_body, (
            "cookie listener callback must be async to support await loadConfig()"
        )
