"""Application configuration using pydantic-settings v2.

Settings are loaded from environment variables.
Nested settings use DB__ and SCRAPING__ prefixes via env_nested_delimiter="__".

Usage:
    from config.settings import Settings
    settings = Settings()
"""

from typing import Literal

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseModel):
    """PostgreSQL connection and pool settings. Sourced from DB__* env vars."""

    host: str
    port: int = 5432
    name: str
    user: str
    password: str
    pool_size: int = 5
    max_overflow: int = 10
    pool_timeout: int = 30


class ScrapingSettings(BaseModel):
    """Scraper retry and timing settings. Sourced from SCRAPING__* env vars."""

    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0
    request_timeout: int = 30


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
