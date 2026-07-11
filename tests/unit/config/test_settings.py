"""Tests for pydantic-settings configuration.

Validates Settings composition and env var override behavior.
All tests use monkeypatch to set environment variables — no .env file required.
"""

import pytest
from pydantic import SecretStr, ValidationError

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
        monkeypatch.setenv("SCRAPING__WORK_SERVER_TOKEN", "test-token")
        settings = Settings()  # type: ignore[call-arg]
        assert settings.db.host == "myhost"

    def test_db_port_defaults_to_5432(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DB__HOST", "localhost")
        monkeypatch.setenv("DB__NAME", "testdb")
        monkeypatch.setenv("DB__USER", "testuser")
        monkeypatch.setenv("DB__PASSWORD", "testpass")
        monkeypatch.setenv("SCRAPING__WORK_SERVER_TOKEN", "test-token")
        settings = Settings()  # type: ignore[call-arg]
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
            Settings(_env_file=None)  # type: ignore[call-arg]

    def test_db_pool_size_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DB__HOST", "localhost")
        monkeypatch.setenv("DB__NAME", "testdb")
        monkeypatch.setenv("DB__USER", "testuser")
        monkeypatch.setenv("DB__PASSWORD", "testpass")
        monkeypatch.setenv("SCRAPING__WORK_SERVER_TOKEN", "test-token")
        settings = Settings()  # type: ignore[call-arg]
        assert settings.db.pool_size == 5

    def test_db_pool_size_overridden(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DB__HOST", "localhost")
        monkeypatch.setenv("DB__NAME", "testdb")
        monkeypatch.setenv("DB__USER", "testuser")
        monkeypatch.setenv("DB__PASSWORD", "testpass")
        monkeypatch.setenv("SCRAPING__WORK_SERVER_TOKEN", "test-token")
        monkeypatch.setenv("DB__POOL_SIZE", "10")
        settings = Settings()  # type: ignore[call-arg]
        assert settings.db.pool_size == 10

    def test_password_not_exposed_in_repr(self) -> None:
        """DatabaseSettings repr must not leak the password value."""
        db = DatabaseSettings(
            host="localhost",
            port=5432,
            name="testdb",
            user="testuser",
            password=SecretStr("supersecret"),
        )
        assert "supersecret" not in repr(db)

    def test_password_accessible_via_get_secret_value(self) -> None:
        """DatabaseSettings.password.get_secret_value() must return the raw string."""
        db = DatabaseSettings(
            host="localhost",
            port=5432,
            name="testdb",
            user="testuser",
            password=SecretStr("mypassword"),
        )
        assert db.password.get_secret_value() == "mypassword"


class TestScrapingSettings:
    def test_scraping_max_retries_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DB__HOST", "localhost")
        monkeypatch.setenv("DB__NAME", "testdb")
        monkeypatch.setenv("DB__USER", "testuser")
        monkeypatch.setenv("DB__PASSWORD", "testpass")
        monkeypatch.setenv("SCRAPING__WORK_SERVER_TOKEN", "test-token")
        settings = Settings()  # type: ignore[call-arg]
        assert settings.scraping.max_retries == 3

    def test_scraping_base_delay_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DB__HOST", "localhost")
        monkeypatch.setenv("DB__NAME", "testdb")
        monkeypatch.setenv("DB__USER", "testuser")
        monkeypatch.setenv("DB__PASSWORD", "testpass")
        monkeypatch.setenv("SCRAPING__WORK_SERVER_TOKEN", "test-token")
        settings = Settings()  # type: ignore[call-arg]
        assert settings.scraping.base_delay == 1.0

    def test_scraping_max_retries_overridden(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DB__HOST", "localhost")
        monkeypatch.setenv("DB__NAME", "testdb")
        monkeypatch.setenv("DB__USER", "testuser")
        monkeypatch.setenv("DB__PASSWORD", "testpass")
        monkeypatch.setenv("SCRAPING__WORK_SERVER_TOKEN", "test-token")
        monkeypatch.setenv("SCRAPING__MAX_RETRIES", "5")
        settings = Settings()  # type: ignore[call-arg]
        assert settings.scraping.max_retries == 5


class TestScrapingSettingsWorkServer:
    def test_work_server_url_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """work_server_url defaults to http://localhost:9731 when env var is absent."""
        monkeypatch.setenv("DB__HOST", "localhost")
        monkeypatch.setenv("DB__NAME", "testdb")
        monkeypatch.setenv("DB__USER", "testuser")
        monkeypatch.setenv("DB__PASSWORD", "testpass")
        monkeypatch.setenv("SCRAPING__WORK_SERVER_TOKEN", "test-token")
        monkeypatch.delenv("SCRAPING__WORK_SERVER_URL", raising=False)
        settings = Settings()  # type: ignore[call-arg]
        assert settings.scraping.work_server_url == "http://localhost:9731"

    def test_empty_work_server_token_raises_in_dev(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Empty SCRAPING__WORK_SERVER_TOKEN raises ValidationError in dev."""
        monkeypatch.setenv("DB__HOST", "localhost")
        monkeypatch.setenv("DB__NAME", "testdb")
        monkeypatch.setenv("DB__USER", "testuser")
        monkeypatch.setenv("DB__PASSWORD", "testpass")
        monkeypatch.delenv("ENV", raising=False)
        monkeypatch.delenv("SCRAPING__WORK_SERVER_TOKEN", raising=False)
        with pytest.raises(ValidationError):
            Settings(_env_file=None)  # type: ignore[call-arg]

    def test_empty_string_work_server_token_raises_in_dev(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Explicit empty string SCRAPING__WORK_SERVER_TOKEN raises ValidationError."""
        monkeypatch.setenv("DB__HOST", "localhost")
        monkeypatch.setenv("DB__NAME", "testdb")
        monkeypatch.setenv("DB__USER", "testuser")
        monkeypatch.setenv("DB__PASSWORD", "testpass")
        monkeypatch.delenv("ENV", raising=False)
        monkeypatch.setenv("SCRAPING__WORK_SERVER_TOKEN", "")
        with pytest.raises(ValidationError):
            Settings()  # type: ignore[call-arg]

    def test_work_server_url_overridden_by_env_var(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SCRAPING__WORK_SERVER_URL env var sets settings.scraping.work_server_url."""
        monkeypatch.setenv("DB__HOST", "localhost")
        monkeypatch.setenv("DB__NAME", "testdb")
        monkeypatch.setenv("DB__USER", "testuser")
        monkeypatch.setenv("DB__PASSWORD", "testpass")
        monkeypatch.setenv("SCRAPING__WORK_SERVER_TOKEN", "test-token")
        monkeypatch.setenv("SCRAPING__WORK_SERVER_URL", "http://example.com:9731")
        settings = Settings()  # type: ignore[call-arg]
        assert settings.scraping.work_server_url == "http://example.com:9731"

    def test_work_server_token_overridden_by_env_var(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SCRAPING__WORK_SERVER_TOKEN env var sets
        settings.scraping.work_server_token."""
        monkeypatch.setenv("DB__HOST", "localhost")
        monkeypatch.setenv("DB__NAME", "testdb")
        monkeypatch.setenv("DB__USER", "testuser")
        monkeypatch.setenv("DB__PASSWORD", "testpass")
        monkeypatch.setenv("SCRAPING__WORK_SERVER_TOKEN", "mysecrettoken")
        settings = Settings()  # type: ignore[call-arg]
        assert settings.scraping.work_server_token.get_secret_value() == "mysecrettoken"

    def test_prod_with_empty_token_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DB__HOST", "localhost")
        monkeypatch.setenv("DB__NAME", "testdb")
        monkeypatch.setenv("DB__USER", "testuser")
        monkeypatch.setenv("DB__PASSWORD", "testpass")
        monkeypatch.setenv("DB__SSL_MODE", "require")
        monkeypatch.setenv("ENV", "prod")
        monkeypatch.delenv("SCRAPING__WORK_SERVER_TOKEN", raising=False)
        monkeypatch.setenv("SCRAPING__WORK_SERVER_URL", "https://example.com:9731")
        with pytest.raises(ValidationError):
            Settings(_env_file=None)  # type: ignore[call-arg]

    def test_prod_with_http_work_server_url_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DB__HOST", "localhost")
        monkeypatch.setenv("DB__NAME", "testdb")
        monkeypatch.setenv("DB__USER", "testuser")
        monkeypatch.setenv("DB__PASSWORD", "testpass")
        monkeypatch.setenv("DB__SSL_MODE", "require")
        monkeypatch.setenv("ENV", "prod")
        monkeypatch.setenv("SCRAPING__WORK_SERVER_TOKEN", "mytoken")
        monkeypatch.setenv("SCRAPING__WORK_SERVER_URL", "http://example.com:9731")
        with pytest.raises(ValidationError):
            Settings()  # type: ignore[call-arg]

    def test_work_server_token_not_exposed_in_repr(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SecretStr token must not appear in Settings repr."""
        monkeypatch.setenv("DB__HOST", "localhost")
        monkeypatch.setenv("DB__NAME", "testdb")
        monkeypatch.setenv("DB__USER", "testuser")
        monkeypatch.setenv("DB__PASSWORD", "testpass")
        monkeypatch.setenv("SCRAPING__WORK_SERVER_TOKEN", "topsecrettoken")
        settings = Settings()  # type: ignore[call-arg]
        assert "topsecrettoken" not in repr(settings)


class TestScrapingSettingsNewFields:
    def test_allowed_hosts_default(self) -> None:
        settings = ScrapingSettings()
        assert settings.allowed_hosts == ["fbref.com"]

    def test_max_concurrent_requests_default(self) -> None:
        settings = ScrapingSettings()
        assert settings.max_concurrent_requests == 3

    def test_request_delay_min_default(self) -> None:
        settings = ScrapingSettings()
        assert settings.request_delay_min == 3.0

    def test_request_delay_max_default(self) -> None:
        settings = ScrapingSettings()
        assert settings.request_delay_max == 10.0

    def test_max_queue_retries_default(self) -> None:
        settings = ScrapingSettings()
        assert settings.max_queue_retries == 5

    def test_request_delay_min_rejects_negative(self) -> None:
        with pytest.raises(ValidationError):
            ScrapingSettings(request_delay_min=-1.0)

    def test_request_delay_max_rejects_negative(self) -> None:
        with pytest.raises(ValidationError):
            ScrapingSettings(request_delay_max=-0.1)

    def test_allowed_hosts_overridden_by_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SCRAPING__ALLOWED_HOSTS env var overrides the default via Settings."""
        monkeypatch.setenv("DB__HOST", "localhost")
        monkeypatch.setenv("DB__NAME", "testdb")
        monkeypatch.setenv("DB__USER", "testuser")
        monkeypatch.setenv("DB__PASSWORD", "testpass")
        monkeypatch.setenv("SCRAPING__WORK_SERVER_TOKEN", "test-token")
        monkeypatch.setenv(
            "SCRAPING__ALLOWED_HOSTS", '["fbref.com","stathead.com"]'
        )
        settings = Settings()  # type: ignore[call-arg]
        assert settings.scraping.allowed_hosts == ["fbref.com", "stathead.com"]


class TestSettings:
    def test_env_defaults_to_dev(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DB__HOST", "localhost")
        monkeypatch.setenv("DB__NAME", "testdb")
        monkeypatch.setenv("DB__USER", "testuser")
        monkeypatch.setenv("DB__PASSWORD", "testpass")
        monkeypatch.setenv("SCRAPING__WORK_SERVER_TOKEN", "test-token")
        monkeypatch.delenv("ENV", raising=False)
        settings = Settings()  # type: ignore[call-arg]
        assert settings.env == "dev"

    def test_env_set_to_prod(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DB__HOST", "localhost")
        monkeypatch.setenv("DB__NAME", "testdb")
        monkeypatch.setenv("DB__USER", "testuser")
        monkeypatch.setenv("DB__PASSWORD", "testpass")
        monkeypatch.setenv("DB__SSL_MODE", "require")
        monkeypatch.setenv("ENV", "prod")
        monkeypatch.setenv("SCRAPING__WORK_SERVER_TOKEN", "prodtoken")
        monkeypatch.setenv("SCRAPING__WORK_SERVER_URL", "https://example.com:9731")
        settings = Settings()  # type: ignore[call-arg]
        assert settings.env == "prod"

    def test_prod_without_ssl_mode_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DB__HOST", "localhost")
        monkeypatch.setenv("DB__NAME", "testdb")
        monkeypatch.setenv("DB__USER", "testuser")
        monkeypatch.setenv("DB__PASSWORD", "testpass")
        monkeypatch.setenv("SCRAPING__WORK_SERVER_TOKEN", "test-token")
        monkeypatch.setenv("ENV", "prod")
        monkeypatch.delenv("DB__SSL_MODE", raising=False)
        with pytest.raises(ValidationError):
            Settings()  # type: ignore[call-arg]

    def test_log_level_defaults_to_info(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DB__HOST", "localhost")
        monkeypatch.setenv("DB__NAME", "testdb")
        monkeypatch.setenv("DB__USER", "testuser")
        monkeypatch.setenv("DB__PASSWORD", "testpass")
        monkeypatch.setenv("SCRAPING__WORK_SERVER_TOKEN", "test-token")
        monkeypatch.delenv("LOG_LEVEL", raising=False)
        settings = Settings()  # type: ignore[call-arg]
        assert settings.log_level == "INFO"

    def test_settings_compose_db_and_scraping(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DB__HOST", "dbhost")
        monkeypatch.setenv("DB__NAME", "testdb")
        monkeypatch.setenv("DB__USER", "testuser")
        monkeypatch.setenv("DB__PASSWORD", "testpass")
        monkeypatch.setenv("SCRAPING__WORK_SERVER_TOKEN", "test-token")
        monkeypatch.setenv("SCRAPING__MAX_RETRIES", "7")
        settings = Settings()  # type: ignore[call-arg]
        assert isinstance(settings.db, DatabaseSettings)
        assert isinstance(settings.scraping, ScrapingSettings)
        assert settings.db.host == "dbhost"
        assert settings.scraping.max_retries == 7
