"""SQLModel database models for Secret AGI."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Column, Text
from sqlmodel import Field, SQLModel

# Note: Using string literals instead of importing enums to avoid circular import
# from ..engine.models import ActionType, Allegiance, EventType, Role
from .enums import GameStatus


class Game(SQLModel, table=True):
    """Game session management table."""

    __tablename__ = "games"

    id: str = Field(primary_key=True, default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    deleted_at: datetime | None = Field(default=None, index=True)  # Soft delete
    status: GameStatus = Field(default=GameStatus.ACTIVE, index=True)
    config: dict[str, Any] = Field(sa_column=Column(JSON))  # GameConfig serialized
    current_turn: int = Field(default=0)
    final_outcome: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    game_metadata: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))


class GameStateDB(SQLModel, table=True):
    """Complete game state snapshots table."""

    __tablename__ = "game_states"

    id: str = Field(primary_key=True, default_factory=lambda: str(uuid.uuid4()))
    game_id: str = Field(foreign_key="games.id", index=True)
    turn_number: int = Field(index=True)
    state_data: dict[str, Any] = Field(sa_column=Column(JSON))  # Complete GameState
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    checksum: str = Field()  # SHA256 of state_data for integrity


class PlayerDB(SQLModel, table=True):
    """Player/agent assignments table."""

    __tablename__ = "players"

    id: str = Field(primary_key=True, default_factory=lambda: str(uuid.uuid4()))
    game_id: str = Field(foreign_key="games.id", index=True)
    player_id: str = Field()  # In-game identifier (e.g., "player_1")
    agent_type: str = (
        Field()
    )  # Agent architecture ("RandomPlayer", "HumanPlayer", etc.)
    agent_config: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    role: str = Field()  # Safety, Accelerationist, AGI
    allegiance: str = Field()  # Safety, Acceleration
    alive: bool = Field(default=True)


class Action(SQLModel, table=True):
    """Complete action history table."""

    __tablename__ = "actions"

    id: str = Field(primary_key=True, default_factory=lambda: str(uuid.uuid4()))
    game_id: str = Field(foreign_key="games.id", index=True)
    turn_number: int = Field(index=True)
    player_id: str = Field()  # In-game player ID
    action_type: str = Field()  # nominate, vote_team, etc.
    action_data: dict[str, Any] = Field(
        sa_column=Column(JSON)
    )  # Parameters and metadata
    is_valid: bool | None = Field(
        default=None
    )  # NULL = processing, True/False = result
    error_message: str | None = Field(default=None, sa_column=Column(Text))
    processing_time_ms: int | None = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Event(SQLModel, table=True):
    """Game events stream table."""

    __tablename__ = "events"

    id: str = Field(primary_key=True, default_factory=lambda: str(uuid.uuid4()))
    game_id: str = Field(foreign_key="games.id", index=True)
    turn_number: int = Field(index=True)
    event_type: str = Field()  # state_changed, power_triggered, etc.
    player_id: str | None = Field(default=None)  # Event initiator (if applicable)
    event_data: dict[str, Any] = Field(sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ChatMessage(SQLModel, table=True):
    """Communication history table."""

    __tablename__ = "chat_messages"

    id: str = Field(primary_key=True, default_factory=lambda: str(uuid.uuid4()))
    game_id: str = Field(foreign_key="games.id", index=True)
    turn_number: int = Field(index=True)
    speaker_id: str = Field()  # Player who sent message
    message: str = Field(sa_column=Column(Text))  # Message content
    phase: str = Field()  # Chat phase identifier
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AgentMetric(SQLModel, table=True):
    """Performance tracking table."""

    __tablename__ = "agent_metrics"

    id: str = Field(primary_key=True, default_factory=lambda: str(uuid.uuid4()))
    game_id: str = Field(foreign_key="games.id", index=True)
    player_id: str = Field(index=True)
    turn_number: int = Field(index=True)
    tokens_used: int | None = Field(default=None)
    response_time_ms: int | None = Field(default=None)
    invalid_attempts: int = Field(default=0)
    internal_state_size: int | None = Field(default=None)
    memory_usage_mb: float | None = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# ADK Integration Tables


class ADKSession(SQLModel, table=True):
    """ADK session management table."""

    __tablename__ = "adk_sessions"

    id: str = Field(primary_key=True)  # ADK session.id
    app_name: str = Field(index=True)
    user_id: str = Field(index=True)
    game_id: str | None = Field(foreign_key="games.id", default=None)
    player_id: str | None = Field(default=None)  # Links to game player
    session_state: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_update_time: datetime = Field(
        default_factory=lambda: datetime.now(UTC)
    )  # ADK lastUpdateTime
    is_active: bool = Field(default=True)


class ADKEvent(SQLModel, table=True):
    """ADK session events table."""

    __tablename__ = "adk_events"

    id: str = Field(primary_key=True, default_factory=lambda: str(uuid.uuid4()))
    session_id: str = Field(foreign_key="adk_sessions.id", index=True)
    event_data: dict[str, Any] = Field(sa_column=Column(JSON))  # Complete ADK Event
    sequence_number: int = Field(index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
