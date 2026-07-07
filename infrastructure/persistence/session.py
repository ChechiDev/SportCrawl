"""Async SQLAlchemy session management.

Two responsibilities kept separate (SRP):
- create_session_factory: builds the engine + factory once at app startup.
- get_session: pure context manager; receives a factory, yields a session.

Usage (app startup):
    from config.settings import Settings
    from infrastructure.persistence.session import create_session_factory, get_session

    settings = Settings()
    factory = create_session_factory(settings.db)

    async with get_session(factory) as session:
        result = await session.execute(...)
"""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.engine.url import URL
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config.settings import DatabaseSettings

logger = logging.getLogger(__name__)


def create_session_factory(db: DatabaseSettings) -> async_sessionmaker[AsyncSession]:
    """Build an async engine and session factory from DatabaseSettings.

    Call once at application startup; reuse the returned factory for the
    lifetime of the process so the connection pool is shared.
    """
    dsn = URL.create(
        drivername="postgresql+asyncpg",
        username=db.user,
        password=db.password,
        host=db.host,
        port=db.port,
        database=db.name,
    )
    connect_args: dict[str, object] = {}
    if db.ssl_mode == "require":
        connect_args["ssl"] = True
    elif db.ssl_mode == "disable":
        connect_args["ssl"] = False

    engine = create_async_engine(
        dsn,
        pool_size=db.pool_size,
        max_overflow=db.max_overflow,
        pool_timeout=float(db.pool_timeout),
        pool_recycle=db.pool_recycle,
        pool_pre_ping=True,
        connect_args=connect_args,
    )
    return async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def get_session(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession, None]:
    """Async context manager yielding an AsyncSession.

    The session is closed on context exit regardless of whether an exception
    was raised. The caller owns the transaction (commit / rollback). Satisfies R7.
    """
    session: AsyncSession = factory()
    try:
        yield session
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
