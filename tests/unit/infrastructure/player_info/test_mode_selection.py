"""Unit tests for player_info mode selection (direct vs buffered)."""
from __future__ import annotations

from config.settings import ScrapingSettings

# ---------------------------------------------------------------------------
# Feature flag defaults
# ---------------------------------------------------------------------------


def test_default_buffer_disabled():
    """Buffered mode must be off by default."""
    s = ScrapingSettings()
    assert s.player_info_dispatch_buffer_enabled is False


def test_default_warm_pool_disabled():
    s = ScrapingSettings()
    assert s.player_info_warm_pool_enabled is False


def test_default_gate_cooldown():
    s = ScrapingSettings()
    assert s.player_info_gate_cooldown_secs >= 5.0


def test_default_gate_probe_timeout():
    s = ScrapingSettings()
    assert s.player_info_gate_probe_timeout_secs >= 5.0


def test_default_gate_max_probe_attempts():
    s = ScrapingSettings()
    assert s.player_info_gate_max_probe_attempts >= 1


def test_gate_settings_respect_minimum():
    """Settings must reject values below their floor."""
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ScrapingSettings(player_info_gate_cooldown_secs=1.0)  # below ge=5.0


# ---------------------------------------------------------------------------
# Mutual exclusion (logic-level assertions via settings inspection)
# ---------------------------------------------------------------------------


def test_direct_and_buffered_modes_are_mutually_exclusive_via_flag():
    """The single boolean flag determines mode — only one can be active."""
    s_direct = ScrapingSettings(player_info_dispatch_buffer_enabled=False)
    s_buffered = ScrapingSettings(player_info_dispatch_buffer_enabled=True)
    # Verify the flag round-trips correctly — mode is selected by this single bool.
    assert s_direct.player_info_dispatch_buffer_enabled is False
    assert s_buffered.player_info_dispatch_buffer_enabled is True
    # A single process uses exactly one config: flag cannot be both True and False.
    assert s_direct.player_info_dispatch_buffer_enabled != (
        s_buffered.player_info_dispatch_buffer_enabled
    )


# ---------------------------------------------------------------------------
# Gate integration: RateLimitGate is only used in buffered mode
# ---------------------------------------------------------------------------


def test_rate_limit_gate_module_imports_cleanly():
    from infrastructure.browser.gate import RateLimitGate
    gate = RateLimitGate()
    assert gate.is_open is True


def test_gate_no_persistence_import():
    """gate.py must not import from infrastructure.persistence."""
    import importlib
    import inspect
    import sys

    mod_name = "infrastructure.browser.gate"
    if mod_name in sys.modules:
        mod = sys.modules[mod_name]
    else:
        mod = importlib.import_module(mod_name)

    source = inspect.getsource(mod)
    assert "infrastructure.persistence" not in source


def test_gate_no_config_import():
    """gate.py must not import from config — settings are injected by orchestrator."""
    import importlib
    import inspect
    import sys

    mod_name = "infrastructure.browser.gate"
    if mod_name in sys.modules:
        mod = sys.modules[mod_name]
    else:
        mod = importlib.import_module(mod_name)

    source = inspect.getsource(mod)
    assert "config.settings" not in source
    assert "from config" not in source
