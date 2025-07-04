"""Configuration management for Secret AGI application.

This module provides centralized configuration using Pydantic BaseSettings,
allowing configuration from environment variables, .env files, or defaults.
"""

import os
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings


class DatabaseSettings(BaseSettings):
    """Database configuration settings."""

    # Database URL with environment-aware defaults
    url: str = Field(
        default_factory=lambda: _get_default_database_url(),
        description="Database connection URL",
    )

    # Connection pool settings
    pool_size: int = Field(default=5, description="Connection pool size")
    max_overflow: int = Field(default=10, description="Maximum pool overflow")
    pool_timeout: int = Field(
        default=30, description="Pool connection timeout in seconds"
    )

    # Migration settings
    migration_timeout: int = Field(
        default=300, description="Migration timeout in seconds"
    )

    class Config:
        env_prefix = "SECRET_AGI_DB_"
        env_file = ".env"
        env_file_encoding = "utf-8"


class GameSettings(BaseSettings):
    """Game engine configuration settings."""

    # Default game parameters
    default_max_turns: int = Field(
        default=1000, description="Default maximum turns per game"
    )
    action_timeout_seconds: int = Field(
        default=30, description="Timeout for player actions"
    )

    # Performance settings
    enable_state_compression: bool = Field(
        default=False, description="Enable state JSON compression"
    )
    enable_metrics_collection: bool = Field(
        default=True, description="Enable performance metrics"
    )

    class Config:
        env_prefix = "SECRET_AGI_GAME_"
        env_file = ".env"
        env_file_encoding = "utf-8"


class LoggingSettings(BaseSettings):
    """Logging configuration settings."""

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO", description="Logging level"
    )
    format: str = Field(
        default="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        description="Log message format",
    )

    class Config:
        env_prefix = "SECRET_AGI_LOG_"
        env_file = ".env"
        env_file_encoding = "utf-8"


class Settings(BaseSettings):
    """Main application settings."""

    # Environment
    environment: Literal["development", "testing", "production"] = Field(
        default="development", description="Application environment"
    )

    # Sub-settings
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    game: GameSettings = Field(default_factory=GameSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)

    class Config:
        env_prefix = "SECRET_AGI_"
        env_file = ".env"
        env_file_encoding = "utf-8"


def _get_default_database_url() -> str:
    """Get default database URL based on environment."""
    # Check for explicit environment variable
    if url := os.getenv("SECRET_AGI_DB_URL"):
        return url

    # Check testing environment
    if (
        os.getenv("PYTEST_CURRENT_TEST")
        or os.getenv("SECRET_AGI_ENVIRONMENT") == "testing"
    ):
        return "sqlite:///:memory:"

    # Development default - use file-based SQLite
    project_root = Path(__file__).parent.parent
    db_path = project_root / "secret_agi.db"
    return f"sqlite:///{db_path}"


def get_database_url() -> str:
    """Get the current database URL with proper driver conversion."""
    settings = Settings()
    url = settings.database.url

    # Convert sqlite:// to sqlite+aiosqlite:// for async support
    if url.startswith("sqlite://"):
        url = url.replace("sqlite://", "sqlite+aiosqlite://")

    return url


def get_alembic_database_url() -> str:
    """Get database URL for Alembic migrations (sync driver)."""
    settings = Settings()
    url = settings.database.url

    # Alembic needs sync SQLite driver
    if url.startswith("sqlite+aiosqlite://"):
        url = url.replace("sqlite+aiosqlite://", "sqlite:///")
    elif url == "sqlite:///:memory:":
        # For in-memory databases, use a temporary file for migrations
        project_root = Path(__file__).parent.parent
        temp_db = project_root / "temp_migration.db"
        url = f"sqlite:///{temp_db}"

    return url


# Global settings instance
settings = Settings()
