"""Database connection management for Secret AGI."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ..settings import get_database_url

# Models will be imported when needed to avoid circular imports

# Global engine and session maker
_engine = None
_async_session_maker = None

logger = logging.getLogger(__name__)


async def init_database(database_url: str | None = None, echo: bool = False) -> None:
    """Initialize the database connection and create tables."""
    global _engine, _async_session_maker

    if database_url is None:
        database_url = get_database_url()

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

    # Create tables automatically if they don't exist
    # This handles in-memory databases and new persistent databases
    from sqlmodel import SQLModel
    from sqlalchemy import text

    # Import models to register them with SQLModel
    from . import models  # noqa: F401

    try:
        # Check if tables exist by looking for the games table
        async with _engine.connect() as conn:
            result = await conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name='games'")
            )
            tables_exist = result.fetchone() is not None

        if not tables_exist:
            logger.info("Tables not found, creating database schema...")
            # NOTE: For production databases with existing data, always backup the database
            # file before running migrations or schema changes
            async with _engine.begin() as conn:
                await conn.run_sync(SQLModel.metadata.create_all)
            logger.info("Database tables created successfully")
        else:
            logger.debug("Database tables already exist")
    except Exception as e:
        logger.warning(f"Could not check/create tables: {e}")
        # For in-memory or other cases, try to create anyway
        if ":memory:" in database_url:
            async with _engine.begin() as conn:
                await conn.run_sync(SQLModel.metadata.create_all)

    logger.info(f"Database initialized with URL: {database_url}")


@asynccontextmanager
async def get_async_session() -> AsyncGenerator[AsyncSession]:
    """Get an async database session."""
    if _async_session_maker is None:
        await init_database()

    async with _async_session_maker() as session:  # type: ignore[misc]
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
        logger.info("Database connection closed")


async def check_database_health() -> dict[str, Any]:
    """
    Check database connection health and return status information.

    Returns:
        Dict containing health status, connection info, and any error details.

    Example:
        {
            "healthy": True,
            "database_url": "sqlite+aiosqlite:///:memory:",
            "connection_status": "connected",
            "response_time_ms": 12.5,
            "error": None
        }
    """
    import time

    health_status = {
        "healthy": False,
        "database_url": "unknown",
        "connection_status": "disconnected",
        "response_time_ms": None,
        "error": None,
    }

    try:
        # Get database URL for reporting
        database_url = get_database_url()
        # Mask sensitive parts for logging
        display_url = database_url
        if "://" in display_url and "@" in display_url:
            # Hide password in connection strings like postgresql://user:pass@host/db
            parts = display_url.split("://")
            if len(parts) == 2 and "@" in parts[1]:
                auth_part = parts[1].split("@")[0]
                if ":" in auth_part:
                    user = auth_part.split(":")[0]
                    display_url = f"{parts[0]}://{user}:***@{parts[1].split('@', 1)[1]}"

        health_status["database_url"] = display_url

        # Initialize database if not already done
        if _engine is None:
            await init_database(database_url)

        # Perform a simple query to test connection
        start_time = time.time()
        async with get_async_session() as session:
            # Use a simple SELECT 1 query that works across database types
            result = await session.execute(text("SELECT 1 as health_check"))
            row = result.fetchone()

            if row and row[0] == 1:
                health_status["healthy"] = True
                health_status["connection_status"] = "connected"
            else:
                health_status["error"] = "Unexpected query result"

        end_time = time.time()
        health_status["response_time_ms"] = round((end_time - start_time) * 1000, 2)

    except SQLAlchemyError as e:
        health_status["error"] = f"Database error: {str(e)}"
        health_status["connection_status"] = "error"
        logger.warning(f"Database health check failed: {e}")
    except Exception as e:
        health_status["error"] = f"Unexpected error: {str(e)}"
        health_status["connection_status"] = "error"
        logger.error(f"Database health check failed with unexpected error: {e}")

    return health_status


async def get_database_info() -> dict[str, Any]:
    """
    Get detailed database information for monitoring and debugging.

    Returns:
        Dict containing database configuration and status information.
    """
    from ..settings import settings

    info = {
        "database_url": get_database_url(),
        "pool_size": settings.database.pool_size,
        "max_overflow": settings.database.max_overflow,
        "pool_timeout": settings.database.pool_timeout,
        "environment": settings.environment,
        "engine_initialized": _engine is not None,
        "session_maker_initialized": _async_session_maker is not None,
    }

    # Add engine-specific info if available
    if _engine is not None:
        info.update(
            {
                "engine_pool_size": _engine.pool.size()
                if hasattr(_engine.pool, "size")
                else "unknown",
                "engine_pool_checked_out": _engine.pool.checkedout()
                if hasattr(_engine.pool, "checkedout")
                else "unknown",
            }
        )

    return info
