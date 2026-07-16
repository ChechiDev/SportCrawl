"""Shared test fixtures.

Session-scoped fixtures start a PostgresContainer once per test session and
expose an async SQLAlchemy engine and session to integration tests.
The settings_override fixture yields a DatabaseSettings instance that points
at the container database.
"""

from collections.abc import AsyncGenerator, Generator

import pytest
from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from testcontainers.postgres import PostgresContainer

from pydantic import SecretStr

from config.settings import DatabaseSettings

# ---------------------------------------------------------------------------
# Container (sync, session-scoped)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def postgres_container() -> Generator[PostgresContainer, None, None]:
    """Start a Postgres 16 container once for the entire test session."""
    with PostgresContainer("postgres:16-alpine") as container:
        yield container


# ---------------------------------------------------------------------------
# Async engine (session-scoped)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
async def async_engine(
    postgres_container: PostgresContainer,
) -> AsyncGenerator[AsyncEngine, None]:
    """Create an async SQLAlchemy engine connected to the test container."""
    raw_url = postgres_container.get_connection_url()
    async_url = make_url(raw_url).set(drivername="postgresql+asyncpg")
    engine = create_async_engine(async_url, echo=False)
    yield engine
    await engine.dispose()


# ---------------------------------------------------------------------------
# Async session (function-scoped, new session per test)
# ---------------------------------------------------------------------------


@pytest.fixture
async def async_session(
    async_engine: AsyncEngine,
) -> AsyncGenerator[AsyncSession, None]:
    """Yield an AsyncSession rolled back after each test to guarantee isolation."""
    async with async_engine.connect() as conn:
        await conn.begin()
        await conn.begin_nested()
        session = AsyncSession(bind=conn, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()
            await conn.rollback()


# ---------------------------------------------------------------------------
# Settings override (function-scoped)
# ---------------------------------------------------------------------------


@pytest.fixture
def settings_override(postgres_container: PostgresContainer) -> DatabaseSettings:
    """Return a DatabaseSettings instance pointing at the test container."""
    raw_url = postgres_container.get_connection_url()
    parsed = make_url(raw_url)
    return DatabaseSettings(
        host=str(parsed.host),
        port=int(parsed.port or 5432),
        name=str(parsed.database),
        user=str(parsed.username),
        password=SecretStr(str(parsed.password or "")),
    )
