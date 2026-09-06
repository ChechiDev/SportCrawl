"""Static analysis tests for background.js service-worker resilience patterns."""

import json
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
