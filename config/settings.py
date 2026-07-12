"""Application configuration using pydantic-settings v2.

Settings are loaded from environment variables.
Nested settings use DB__ and SCRAPING__ prefixes via env_nested_delimiter="__".

Usage:
    from config.settings import Settings
    settings = Settings()
"""

from typing import Literal

from pydantic import BaseModel, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseModel):
    """PostgreSQL connection and pool settings. Sourced from DB__* env vars."""

    host: str
    port: int = 5432
    name: str
    user: str
    password: SecretStr
    pool_size: int = 5
    max_overflow: int = 10
    pool_timeout: int = 30
    pool_recycle: int = 1800
    ssl_mode: Literal["require", "disable"] | None = None


class ScrapingSettings(BaseModel):
    """Scraper retry and timing settings. Sourced from SCRAPING__* env vars."""

    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0
    request_timeout: int = 30
    work_server_url: str = "http://localhost:9731"
    work_server_token: SecretStr = SecretStr("")
    allowed_hosts: list[str] = ["fbref.com"]
    max_concurrent_requests: int = 3
    request_delay_min: float = Field(default=3.0, ge=0.0)
    request_delay_max: float = Field(default=10.0, ge=0.0)
    max_queue_retries: int = 5
    # Work server runtime settings
    work_server_host: str = "127.0.0.1"
    work_server_port: int = 9731
    poll_interval: float = Field(default=5.0, gt=0.0)
    # Remote CDP engine — set to connect to a pre-running Chromium container.
    # Example: SCRAPING__CDP_WS_URL=ws://chromium:9222
    cdp_ws_url: str | None = None


class Settings(BaseSettings):
    """Root application settings.

    Reads nested values using double-underscore delimiter:
        DB__HOST → settings.db.host
        SCRAPING__MAX_RETRIES → settings.scraping.max_retries
        ENV → settings.env
        LOG_LEVEL → settings.log_level
    """

    model_config = SettingsConfigDict(
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    db: DatabaseSettings
    scraping: ScrapingSettings = ScrapingSettings()
    env: Literal["dev", "prod"] = "dev"
    log_level: str = "INFO"

    @model_validator(mode="after")
    def enforce_prod_ssl(self) -> "Settings":
        """Require explicit SSL in prod — both None and 'disable' are rejected."""
        if self.env == "prod" and self.db.ssl_mode != "require":
            raise ValueError(
                f"DB__SSL_MODE must be 'require' in prod. Got: {self.db.ssl_mode!r}"
            )
        return self

    @model_validator(mode="after")
    def enforce_work_server_token(self) -> "Settings":
        """Require non-empty SCRAPING__WORK_SERVER_TOKEN in all environments."""
        if not self.scraping.work_server_token.get_secret_value():
            raise ValueError(
                "SCRAPING__WORK_SERVER_TOKEN must be a non-empty value."
            )
        return self

    @model_validator(mode="after")
    def enforce_prod_work_server(self) -> "Settings":
        """Require HTTPS work_server_url in prod."""
        if self.env == "prod":
            if not self.scraping.work_server_url.startswith("https://"):
                raise ValueError(
                    f"SCRAPING__WORK_SERVER_URL must use HTTPS in prod. "
                    f"Got: {self.scraping.work_server_url!r}"
                )
        return self
