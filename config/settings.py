"""Application configuration using pydantic-settings v2.

Settings are loaded from environment variables.
Nested settings use DB__ and SCRAPING__ prefixes via env_nested_delimiter="__".

Usage:
    from config.settings import Settings
    settings = Settings()
"""

from pathlib import Path
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
    work_server_token: SecretStr | None = None
    fbref_base_url: str = "https://fbref.com"
    allowed_hosts: list[str] = ["fbref.com"]
    max_concurrent_requests: int = 3
    request_delay_min: float = Field(default=3.0, ge=0.0)
    request_delay_max: float = Field(default=10.0, ge=0.0)
    max_queue_retries: int = Field(default=5, ge=1)
    scheduling_batch_size: int = 200       # rows per startup drain batch
    # Work server runtime settings
    work_server_host: str = "127.0.0.1"
    work_server_port: int = 9731
    poll_interval: float = Field(default=5.0, gt=0.0)
    # Remote CDP engine — set to connect to a pre-running Chromium container.
    # Example: SCRAPING__CDP_WS_URL=ws://chromium:9222
    cdp_ws_url: str | None = None
    chrome_profile_dir: str = str(Path.home() / ".cache" / "sportcrawl" / "chrome")
    # Warm browser pool (disabled by default — opt-in via feature flag)
    player_info_warm_pool_enabled: bool = False
    player_info_pool_size: int = Field(default=2, ge=1, le=25)
    player_info_pool_browser_start_concurrency: int = Field(default=1, ge=1, le=25)
    player_info_pool_warmup_concurrency: int = Field(default=1, ge=1, le=25)
    player_info_pool_startup_jitter_min: float = Field(default=2.0, ge=0.0)
    player_info_pool_startup_jitter_max: float = Field(default=15.0, ge=0.0)
    player_info_pool_browser_backoff_base: float = Field(default=2.0, ge=0.1)
    player_info_pool_browser_backoff_max: float = Field(default=120.0, ge=1.0)
    player_info_pool_task_backoff_base: float = Field(default=2.0, ge=0.1)
    player_info_pool_task_backoff_max: float = Field(default=60.0, ge=1.0)
    # Dispatch buffer (disabled by default — opt-in via feature flag)
    player_info_dispatch_buffer_enabled: bool = False
    player_info_dispatch_buffer_size: int = Field(default=20, ge=1, le=500)
    player_info_dispatch_buffer_prefetch: int = Field(default=50, ge=1, le=500)
    player_info_dispatch_buffer_poll_interval: float = Field(default=5.0, ge=0.5)
    # Rate-limit gate for buffered player_info mode
    player_info_gate_cooldown_secs: float = Field(default=60.0, ge=5.0)
    player_info_gate_probe_timeout_secs: float = Field(default=30.0, ge=5.0)
    player_info_gate_max_probe_attempts: int = Field(default=3, ge=1, le=10)

    @model_validator(mode="after")
    def validate_warm_pool_ranges(self) -> "ScrapingSettings":
        """Enforce ordering invariants on warm pool config ranges."""
        jmin = self.player_info_pool_startup_jitter_min
        jmax = self.player_info_pool_startup_jitter_max
        if jmin > jmax:
            raise ValueError(
                f"player_info_pool_startup_jitter_min ({jmin}) must be "
                f"<= jitter_max ({jmax})"
            )
        bbase = self.player_info_pool_browser_backoff_base
        bmax = self.player_info_pool_browser_backoff_max
        if bbase > bmax:
            raise ValueError(
                f"player_info_pool_browser_backoff_base ({bbase}) must be "
                f"<= browser_backoff_max ({bmax})"
            )
        tbase = self.player_info_pool_task_backoff_base
        tmax = self.player_info_pool_task_backoff_max
        if tbase > tmax:
            raise ValueError(
                f"player_info_pool_task_backoff_base ({tbase}) must be "
                f"<= task_backoff_max ({tmax})"
            )
        return self


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
        token = self.scraping.work_server_token
        secret = token.get_secret_value() if token is not None else ""
        if not secret:
            raise ValueError("SCRAPING__WORK_SERVER_TOKEN must be a non-empty value.")
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
