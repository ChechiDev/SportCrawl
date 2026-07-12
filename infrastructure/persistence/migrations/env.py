"""Alembic async migration environment.

When application Settings are available (env vars present), the engine is built
directly from a URL object — the password never appears as a plaintext string in
the Alembic config. The alembic.ini sqlalchemy.url is used only as a fallback for
autogenerate offline mode or when Settings can't be loaded.

Run migrations:
    alembic upgrade head
    alembic downgrade -1
"""

import asyncio
import logging
from logging.config import fileConfig

from alembic import context
from pydantic import ValidationError
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.engine.url import URL
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_engine_from_config,
    create_async_engine,
)

# Import Base and all models so their metadata is registered.
import infrastructure.persistence.models.provenance  # noqa: F401, E501  # pyright: ignore[reportUnusedImport]
import infrastructure.persistence.models.scrape_queue  # noqa: F401, E501  # pyright: ignore[reportUnusedImport]
from infrastructure.persistence.migrations._filters import include_name
from infrastructure.persistence.models.base import Base

target_metadata = Base.metadata

alembic_config = context.config

if alembic_config.config_file_name is not None:
    fileConfig(alembic_config.config_file_name)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Attempt to load application Settings.
# Used in run_async_migrations to build the engine without exposing the password
# as a plaintext config string.
# ---------------------------------------------------------------------------

_app_url: URL | None = None

# Priority 1: URL injected by the caller via config.attributes["inject_url"].
# Used by integration test fixtures that pass the testcontainer URL at runtime
# without going through application Settings or alembic.ini.
_injected: URL | None = alembic_config.attributes.get("inject_url")
if _injected is not None:
    _app_url = _injected
else:
    # Priority 2: Application Settings resolved from env vars.
    # ImportError → Settings module not installed (offline tooling).
    # Exception  → env vars missing or invalid (e.g. in test environments).
    try:
        from config.settings import Settings

        # pydantic-settings resolves required fields from env vars at runtime;
        # Pyright cannot observe this dynamic loading —
        # the call-arg suppression is safe.
        _s = Settings()  # type: ignore[call-arg]
        _app_url = URL.create(
            drivername="postgresql+asyncpg",
            username=_s.db.user,
            password=_s.db.password.get_secret_value(),
            host=_s.db.host,
            port=_s.db.port,
            database=_s.db.name,
        )
    except (ImportError, ValidationError):
        logger.warning(
            "Settings not available or env vars missing — "
            "falling back to alembic.ini sqlalchemy.url"
        )
    except Exception:
        logger.error(
            "Unexpected error loading Settings — cannot continue",
            exc_info=True,
        )
        raise


# ---------------------------------------------------------------------------
# Offline migrations (generate SQL without connecting)
# ---------------------------------------------------------------------------


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a live connection."""
    url = _app_url or alembic_config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
        include_name=include_name,
        version_table="alembic_version",
        version_table_schema="sch_infra",
    )
    with context.begin_transaction():
        context.run_migrations()


# ---------------------------------------------------------------------------
# Online migrations (async, connects to Postgres via asyncpg)
# ---------------------------------------------------------------------------


def do_run_migrations(connection: Connection) -> None:
    """Execute pending migrations using a synchronous connection handle."""
    from sqlalchemy import text

    connection.execute(text("CREATE SCHEMA IF NOT EXISTS sch_infra"))
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=True,
        include_name=include_name,
        version_table="alembic_version",
        version_table_schema="sch_infra",
    )
    with context.begin_transaction():
        context.run_migrations()


def _build_engine() -> AsyncEngine:
    """Return an async engine from Settings URL object or alembic.ini fallback."""
    if _app_url is not None:
        return create_async_engine(_app_url, poolclass=pool.NullPool)
    return async_engine_from_config(
        alembic_config.get_section(alembic_config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )


async def run_async_migrations() -> None:
    """Acquire an async engine, then run migrations via run_sync."""
    connectable = _build_engine()
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """Entry point for online migration mode — drives the async runner."""
    asyncio.run(run_async_migrations())


# ---------------------------------------------------------------------------
# Dispatch: offline vs online
# ---------------------------------------------------------------------------

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
