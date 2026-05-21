"""Async SQLAlchemy engine + session factory (asyncpg).

Both are created once during the FastAPI lifespan and stored on ``app.state``.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ..config import BackendConfig


def build_engine(config: BackendConfig) -> AsyncEngine:
    """Create the async engine from the configured DSN."""
    return create_async_engine(config.database_url, pool_pre_ping=True)


def build_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create the async session factory bound to ``engine``."""
    return async_sessionmaker(engine, expire_on_commit=False)
