"""Database package for Secret AGI game persistence."""

from .connection import get_async_session, init_database
from .models import (
    Action,
    ADKEvent,
    # ADK integration tables
    ADKSession,
    AgentMetric,
    ChatMessage,
    Event,
    # Core tables
    Game,
    GameStateDB,
    # Enums
    GameStatus,
    PlayerDB,
)
from .operations import GameOperations

__all__ = [
    # Connection management
    "init_database",
    "get_async_session",
    # Models
    "Game",
    "GameStateDB",
    "PlayerDB",
    "Action",
    "Event",
    "ChatMessage",
    "AgentMetric",
    "ADKSession",
    "ADKEvent",
    "GameStatus",
    # Operations
    "GameOperations",
]
