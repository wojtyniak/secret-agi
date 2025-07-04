"""Database connection management for Secret AGI."""

import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Import all models to ensure they're registered with SQLModel
from .models import (  # noqa: F401
    Action,
    ADKEvent,
    ADKSession,
    AgentMetric,
    ChatMessage,
    Event,
    Game,
    GameStateDB,
    PlayerDB,
)

# Global engine and session maker
_engine = None
_async_session_maker = None


def get_database_url() -> str:
    """Get the database URL from environment or use default SQLite."""
    return os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./secret_agi.db")


async def init_database(database_url: str | None = None, echo: bool = False) -> None:
    """Initialize the database connection and create tables."""
    global _engine, _async_session_maker

    if database_url is None:
        database_url = get_database_url()

    # Ensure SQLite URLs use aiosqlite driver
    if database_url.startswith("sqlite://"):
        database_url = database_url.replace("sqlite://", "sqlite+aiosqlite://")

    # Create async engine
    _engine = create_async_engine(
        database_url,
        echo=echo,
        # SQLite-specific options for JSON1 extension
        connect_args={"check_same_thread": False} if "sqlite" in database_url else {},
    )

    # Create session maker
    _async_session_maker = async_sessionmaker(
        bind=_engine, class_=AsyncSession, expire_on_commit=False
    )

    # For in-memory databases, create tables directly since Alembic won't run
    if ":memory:" in database_url:
        from sqlmodel import SQLModel
        async with _engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)


@asynccontextmanager
async def get_async_session() -> AsyncGenerator[AsyncSession]:
    """Get an async database session."""
    if _async_session_maker is None:
        await init_database()

    async with _async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def close_database() -> None:
    """Close the database connection."""
    global _engine, _async_session_maker
    if _engine:
        await _engine.dispose()
        _engine = None
        _async_session_maker = None
