"""Tests for pydantic-settings configuration.

Validates Settings composition and env var override behavior.
All tests use monkeypatch to set environment variables — no .env file required.
"""

import pytest
from pydantic import ValidationError

from config.settings import DatabaseSettings, ScrapingSettings, Settings


class TestDatabaseSettings:
    def test_db_host_overridden_by_env_var(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """DB__HOST env var sets settings.db.host."""
        monkeypatch.setenv("DB__HOST", "myhost")
        monkeypatch.setenv("DB__PORT", "5432")
        monkeypatch.setenv("DB__NAME", "testdb")
        monkeypatch.setenv("DB__USER", "testuser")
        monkeypatch.setenv("DB__PASSWORD", "testpass")
        settings = Settings()
        assert settings.db.host == "myhost"

    def test_db_port_defaults_to_5432(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DB__HOST", "localhost")
        monkeypatch.setenv("DB__NAME", "testdb")
        monkeypatch.setenv("DB__USER", "testuser")
        monkeypatch.setenv("DB__PASSWORD", "testpass")
        settings = Settings()
        assert settings.db.port == 5432

    def test_missing_db_password_raises_validation_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Missing required DB__PASSWORD raises ValidationError."""
        monkeypatch.delenv("DB__PASSWORD", raising=False)
        monkeypatch.delenv("DB__HOST", raising=False)
        monkeypatch.delenv("DB__NAME", raising=False)
        monkeypatch.delenv("DB__USER", raising=False)
        with pytest.raises(ValidationError):
            Settings()

    def test_db_pool_size_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DB__HOST", "localhost")
        monkeypatch.setenv("DB__NAME", "testdb")
        monkeypatch.setenv("DB__USER", "testuser")
        monkeypatch.setenv("DB__PASSWORD", "testpass")
        settings = Settings()
        assert settings.db.pool_size == 5

    def test_db_pool_size_overridden(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DB__HOST", "localhost")
        monkeypatch.setenv("DB__NAME", "testdb")
        monkeypatch.setenv("DB__USER", "testuser")
        monkeypatch.setenv("DB__PASSWORD", "testpass")
        monkeypatch.setenv("DB__POOL_SIZE", "10")
        settings = Settings()
        assert settings.db.pool_size == 10


class TestScrapingSettings:
    def test_scraping_max_retries_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DB__HOST", "localhost")
        monkeypatch.setenv("DB__NAME", "testdb")
        monkeypatch.setenv("DB__USER", "testuser")
        monkeypatch.setenv("DB__PASSWORD", "testpass")
        settings = Settings()
        assert settings.scraping.max_retries == 3

    def test_scraping_base_delay_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DB__HOST", "localhost")
        monkeypatch.setenv("DB__NAME", "testdb")
        monkeypatch.setenv("DB__USER", "testuser")
        monkeypatch.setenv("DB__PASSWORD", "testpass")
        settings = Settings()
        assert settings.scraping.base_delay == 1.0

    def test_scraping_max_retries_overridden(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DB__HOST", "localhost")
        monkeypatch.setenv("DB__NAME", "testdb")
        monkeypatch.setenv("DB__USER", "testuser")
        monkeypatch.setenv("DB__PASSWORD", "testpass")
        monkeypatch.setenv("SCRAPING__MAX_RETRIES", "5")
        settings = Settings()
        assert settings.scraping.max_retries == 5


class TestSettings:
    def test_env_defaults_to_dev(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DB__HOST", "localhost")
        monkeypatch.setenv("DB__NAME", "testdb")
        monkeypatch.setenv("DB__USER", "testuser")
        monkeypatch.setenv("DB__PASSWORD", "testpass")
        monkeypatch.delenv("ENV", raising=False)
        settings = Settings()
        assert settings.env == "dev"

    def test_env_set_to_prod(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DB__HOST", "localhost")
        monkeypatch.setenv("DB__NAME", "testdb")
        monkeypatch.setenv("DB__USER", "testuser")
        monkeypatch.setenv("DB__PASSWORD", "testpass")
        monkeypatch.setenv("DB__SSL_MODE", "require")
        monkeypatch.setenv("ENV", "prod")
        settings = Settings()
        assert settings.env == "prod"

    def test_prod_without_ssl_mode_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DB__HOST", "localhost")
        monkeypatch.setenv("DB__NAME", "testdb")
        monkeypatch.setenv("DB__USER", "testuser")
        monkeypatch.setenv("DB__PASSWORD", "testpass")
        monkeypatch.setenv("ENV", "prod")
        monkeypatch.delenv("DB__SSL_MODE", raising=False)
        with pytest.raises(ValidationError):
            Settings()

    def test_log_level_defaults_to_info(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DB__HOST", "localhost")
        monkeypatch.setenv("DB__NAME", "testdb")
        monkeypatch.setenv("DB__USER", "testuser")
        monkeypatch.setenv("DB__PASSWORD", "testpass")
        monkeypatch.delenv("LOG_LEVEL", raising=False)
        settings = Settings()
        assert settings.log_level == "INFO"

    def test_settings_compose_db_and_scraping(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DB__HOST", "dbhost")
        monkeypatch.setenv("DB__NAME", "testdb")
        monkeypatch.setenv("DB__USER", "testuser")
        monkeypatch.setenv("DB__PASSWORD", "testpass")
        monkeypatch.setenv("SCRAPING__MAX_RETRIES", "7")
        settings = Settings()
        assert isinstance(settings.db, DatabaseSettings)
        assert isinstance(settings.scraping, ScrapingSettings)
        assert settings.db.host == "dbhost"
        assert settings.scraping.max_retries == 7
