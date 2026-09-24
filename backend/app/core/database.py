"""Async SQLAlchemy engine, session factory and FastAPI dependency."""
from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from .config import get_settings


class Base(DeclarativeBase):
    """Declarative base shared by all ORM models."""


class Database:
    """Own the async engine and the transactional session factory.

    The engine is created lazily by SQLAlchemy; no connection is opened until
    the first query. Call :meth:`dispose` during application shutdown to close
    the underlying connection pool.
    """

    def __init__(self, url: str, echo: bool = False) -> None:
        self._url = url
        self.engine = create_async_engine(url, echo=echo, pool_pre_ping=True)
        self.session_factory = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    async def dispose(self) -> None:
        """Dispose of the connection pool, releasing all connections."""
        await self.engine.dispose()

    async def create_all(self) -> None:
        """Create all registered tables (development convenience).

        Prefer Alembic migrations or ``migrations/init.sql`` for schema changes;
        this exists only to bootstrap a local environment quickly.
        """
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)


@lru_cache
def get_database() -> Database:
    """Return a process-wide cached :class:`Database` instance."""
    settings = get_settings()
    return Database(settings.database_url)


async def get_db() -> AsyncIterator[AsyncSession]:
    """Yield a transactional async session, committing on success.

    Used as a FastAPI dependency: ``session: AsyncSession = Depends(get_db)``.
    The transaction is rolled back automatically if the request raises.
    """
    database = get_database()
    async with database.session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
