"""Integration test fixtures.

Provides isolated integration test infrastructure that avoids asyncpg
cross-event-loop issues.

Design:
- ``_integration_postgres``: one Postgres container per test session
  (sync, session-scoped).
- ``_integration_db_url``: derives the asyncpg URL object from the container
  (sync, session-scoped). NOTE: must remain a SQLAlchemy URL object, NOT a
  str — str() masks the password.
- ``migrate_db``: creates the schema once using ``asyncio.run()`` in a
  dedicated loop, outside pytest-asyncio's loop management
  (sync, session-scoped, autouse).
- ``async_session``: yields a fresh ``AsyncSession`` per test function,
  creating a new engine inside the test's own event loop to avoid
  cross-loop asyncpg errors.
"""

import asyncio
from collections.abc import AsyncGenerator, Generator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.engine.url import URL, make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from testcontainers.postgres import PostgresContainer

import infrastructure.persistence.models.scrape_queue  # noqa: F401
from infrastructure.persistence.models.base import Base

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
# Schema creation (sync fixture using asyncio.run — avoids pytest-asyncio loops)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def migrate_db(_integration_db_url: URL) -> None:
    """Create all tables once for the integration test session.

    Runs ``Base.metadata.create_all`` via a dedicated ``asyncio.run()`` call
    so it is completely independent of pytest-asyncio's loop management.
    """

    async def _create_all() -> None:
        engine = create_async_engine(_integration_db_url, echo=False)
        try:
            async with engine.begin() as conn:
                # sch_infra must exist before create_all — SQLAlchemy emits
                # CREATE TABLE sch_infra.scrape_queue but never creates the schema.
                await conn.execute(text("CREATE SCHEMA IF NOT EXISTS sch_infra"))
                await conn.run_sync(Base.metadata.create_all)
        finally:
            await engine.dispose()

    asyncio.run(_create_all())


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
