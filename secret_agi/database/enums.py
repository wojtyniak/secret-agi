"""Database-specific enums for Secret AGI."""

from enum import Enum


class GameStatus(str, Enum):
    """Game status values for database storage."""

    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"


class RecoveryType(str, Enum):
    """Types of recovery scenarios."""

    INCOMPLETE_ACTION = "incomplete_action"
    AGENT_TIMEOUT = "agent_timeout"
    TRANSACTION_FAILURE = "transaction_failure"
    UNKNOWN = "unknown"
