"""Integration test fixtures.

Provides isolated integration test infrastructure that avoids asyncpg
cross-event-loop issues.

Design:
- ``_integration_postgres``: one Postgres container per test session
  (sync, session-scoped).
- ``_integration_db_url``: derives the asyncpg URL object from the container
  (sync, session-scoped). NOTE: must remain a SQLAlchemy URL object, NOT a
  str — str() masks the password.
- ``migrate_db``: runs ``alembic upgrade head`` programmatically against the
  testcontainer, injecting the URL via ``config.attributes["inject_url"]``.
  This installs the full migration chain including DB triggers.
  (sync, session-scoped, autouse).
- ``async_session``: yields a fresh ``AsyncSession`` per test function,
  creating a new engine inside the test's own event loop to avoid
  cross-loop asyncpg errors.
"""

import os
from collections.abc import AsyncGenerator, Generator

import pytest
import pytest_asyncio
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from sqlalchemy.engine.url import URL, make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from testcontainers.postgres import PostgresContainer

# ---------------------------------------------------------------------------
# Container fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def _integration_postgres() -> Generator[PostgresContainer, None, None]:
    """Start a dedicated Postgres 16 container for the integration test session."""
    with PostgresContainer("postgres:16-alpine") as container:
        yield container


@pytest.fixture(scope="session")
def _integration_db_url(_integration_postgres: PostgresContainer) -> URL:
    """Return the asyncpg-compatible URL object for the test container.

    IMPORTANT: returns a SQLAlchemy ``URL`` object, not a plain string.
    Calling ``str()`` on a SQLAlchemy URL masks the password with ``***``,
    which causes asyncpg authentication failures.
    """
    raw_url = _integration_postgres.get_connection_url()
    return make_url(raw_url).set(drivername="postgresql+asyncpg")


# ---------------------------------------------------------------------------
# Schema migration (runs alembic upgrade head — installs triggers + full DDL)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def migrate_db(_integration_db_url: URL) -> None:
    """Run ``alembic upgrade head`` once for the integration test session.

    Injects the testcontainer URL via ``alembic_config.attributes["inject_url"]``
    so ``env.py`` uses it instead of application Settings or alembic.ini.

    Using ``alembic upgrade head`` (instead of ``Base.metadata.create_all``)
    ensures the full migration chain runs, including:
    - ``CREATE SCHEMA IF NOT EXISTS sch_infra`` (migration a3f8c1d29e5b)
    - The ``trg_scrape_queue_updated_at`` trigger (migration 134f2e68682a)
    """
    ini_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "alembic.ini"
    )
    ini_path = os.path.normpath(ini_path)

    cfg = AlembicConfig(ini_path)
    # Inject the asyncpg URL into env.py via config.attributes so that
    # env.py's _build_engine() uses it rather than loading Settings or alembic.ini.
    cfg.attributes["inject_url"] = _integration_db_url

    alembic_command.upgrade(cfg, "head")


# ---------------------------------------------------------------------------
# Function-scoped async_session (fresh engine per test)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(loop_scope="function")
async def async_session(
    _integration_db_url: URL,
) -> AsyncGenerator[AsyncSession, None]:
    """Yield an ``AsyncSession`` backed by a fresh engine for each test function.

    Creating a new engine per test ensures asyncpg connections are always
    bound to the test function's own event loop, avoiding the
    ``Future attached to a different loop`` error that occurs when a
    session-scoped engine is reused across function-scoped coroutines.

    The session's transaction is rolled back after the test so data written
    during the test never persists to subsequent tests.
    """
    engine = create_async_engine(_integration_db_url, echo=False)
    try:
        async with engine.connect() as conn:
            await conn.begin()
            async with AsyncSession(bind=conn, expire_on_commit=False) as session:
                yield session
            await conn.rollback()
    finally:
        await engine.dispose()
