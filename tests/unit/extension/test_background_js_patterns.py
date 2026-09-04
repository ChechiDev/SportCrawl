"""Static analysis tests for background.js service-worker resilience patterns."""

from pathlib import Path

_BG = (
    Path(__file__).parents[3] / "extensions" / "sportcrawl-chrome" / "background.js"
).read_text()


class TestCookieListenerResilience:
    def test_cookie_listener_calls_load_config_before_readiness_check(self) -> None:
        listener_start = _BG.index("chrome.cookies.onChanged.addListener")
        listener_body = _BG[listener_start:]

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
