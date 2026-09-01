# tests/unit/cli/test_extension_config.py
"""Unit tests for ExtensionConfig — strict TDD RED/GREEN cycle.

No real browser, network, DB, or CDP.
"""

from __future__ import annotations

import pytest

from cli.extension_config import ExtensionConfig, smoke_extension_config

_SENTINEL_TOKEN = "SENTINEL_TOKEN_VALUE_MUST_NOT_LEAK"
_SENTINEL_URL = "http://127.0.0.1:9731"


class TestExtensionConfigFields:
    def test_profile_id_smoke_matches_regex(self) -> None:
        import re

        _ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
        cfg = ExtensionConfig(
            work_server_url=_SENTINEL_URL,
            work_server_token=_SENTINEL_TOKEN,
            profile_id="smoke",
            worker_id="smoke",
            disable_task_polling=True,
        )
        assert _ID_RE.match(cfg.profile_id) is not None

    def test_worker_id_smoke_matches_regex(self) -> None:
        import re

        _ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
        cfg = ExtensionConfig(
            work_server_url=_SENTINEL_URL,
            work_server_token=_SENTINEL_TOKEN,
            profile_id="smoke",
            worker_id="smoke",
            disable_task_polling=True,
        )
        assert _ID_RE.match(cfg.worker_id) is not None

    def test_disable_task_polling_is_true_for_smoke_config(self) -> None:
        cfg = smoke_extension_config(url=_SENTINEL_URL, token=_SENTINEL_TOKEN)
        assert cfg.disable_task_polling is True

    def test_repr_does_not_contain_token_value(self) -> None:
        cfg = ExtensionConfig(
            work_server_url=_SENTINEL_URL,
            work_server_token=_SENTINEL_TOKEN,
            profile_id="smoke",
            worker_id="smoke",
            disable_task_polling=True,
        )
        assert _SENTINEL_TOKEN not in repr(cfg)
        assert _SENTINEL_TOKEN not in str(cfg)

    def test_str_does_not_contain_token_value(self) -> None:
        cfg = smoke_extension_config(url=_SENTINEL_URL, token=_SENTINEL_TOKEN)
        assert _SENTINEL_TOKEN not in str(cfg)


class TestExtensionConfigValidation:
    def test_invalid_profile_id_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="profile_id"):
            ExtensionConfig(
                work_server_url=_SENTINEL_URL,
                work_server_token=_SENTINEL_TOKEN,
                profile_id="invalid id with spaces",
                worker_id="smoke",
                disable_task_polling=True,
            )

    def test_empty_profile_id_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="profile_id"):
            ExtensionConfig(
                work_server_url=_SENTINEL_URL,
                work_server_token=_SENTINEL_TOKEN,
                profile_id="",
                worker_id="smoke",
                disable_task_polling=True,
            )

    def test_invalid_worker_id_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="worker_id"):
            ExtensionConfig(
                work_server_url=_SENTINEL_URL,
                work_server_token=_SENTINEL_TOKEN,
                profile_id="smoke",
                worker_id="bad!worker",
                disable_task_polling=True,
            )

    def test_too_long_profile_id_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="profile_id"):
            ExtensionConfig(
                work_server_url=_SENTINEL_URL,
                work_server_token=_SENTINEL_TOKEN,
                profile_id="a" * 65,
                worker_id="smoke",
                disable_task_polling=True,
            )


class TestSmokeExtensionConfigFactory:
    def test_factory_sets_profile_id_to_smoke(self) -> None:
        cfg = smoke_extension_config(url=_SENTINEL_URL, token=_SENTINEL_TOKEN)
        assert cfg.profile_id == "smoke"

    def test_factory_sets_worker_id_to_smoke(self) -> None:
        cfg = smoke_extension_config(url=_SENTINEL_URL, token=_SENTINEL_TOKEN)
        assert cfg.worker_id == "smoke"

    def test_factory_sets_disable_task_polling_true(self) -> None:
        cfg = smoke_extension_config(url=_SENTINEL_URL, token=_SENTINEL_TOKEN)
        assert cfg.disable_task_polling is True
