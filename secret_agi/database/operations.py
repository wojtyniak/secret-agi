"""Database operations for Secret AGI."""

import hashlib
import json
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from sqlalchemy import and_, exists, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

# if TYPE_CHECKING:
#     from ..engine.models import GameConfig
from .enums import GameStatus, RecoveryType
from .models import (
    Action,
    AgentMetric,
    ChatMessage,
    Event,
    Game,
    GameStateDB,
)


class GameOperations:
    """Database operations for game management."""

    @staticmethod
    def _serialize_enums(data: Any) -> Any:
        """Recursively convert enums to strings for JSON serialization."""
        if isinstance(data, Enum):
            return data.value
        elif isinstance(data, dict):
            return {
                key: GameOperations._serialize_enums(value)
                for key, value in data.items()
            }
        elif isinstance(data, list):
            return [GameOperations._serialize_enums(item) for item in data]
        else:
            return data

    @staticmethod
    def _deserialize_enums(data: Any) -> Any:
        """Reconstruct enums from JSON data (placeholder for future implementation)."""
        # For now, return as-is. This would need enum type mapping for full deserialization
        return data

    @staticmethod
    async def create_game(session: AsyncSession, config: Any) -> str:
        """Create a new game in the database."""
        game_id = str(uuid.uuid4())

        game = Game(
            id=game_id,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            status=GameStatus.ACTIVE,
            config=asdict(config),
            current_turn=0,
        )

        session.add(game)
        await session.commit()
        return game_id

    @staticmethod
    async def save_game_state(
        session: AsyncSession, game_id: str, turn: int, state: Any
    ) -> str:
        """Save a complete game state snapshot."""
        state_id = str(uuid.uuid4())
        state_data = asdict(state)

        # Convert enums to strings for JSON serialization
        state_data = GameOperations._serialize_enums(state_data)

        # Generate checksum for integrity
        checksum = hashlib.sha256(
            json.dumps(state_data, sort_keys=True).encode()
        ).hexdigest()

        state_record = GameStateDB(
            id=state_id,
            game_id=game_id,
            turn_number=turn,
            state_data=state_data,
            created_at=datetime.now(UTC),
            checksum=checksum,
        )

        session.add(state_record)
        await session.commit()
        return state_id

    @staticmethod
    async def load_game_state(
        session: AsyncSession, game_id: str, turn: int | None = None
    ) -> dict[str, Any] | None:
        """Load a game state from the database (only for non-deleted games)."""
        # First check if the game exists and is not deleted
        game_query = select(Game).where(
            and_(Game.id == game_id, Game.deleted_at == None)  # type: ignore
        )
        game_result = await session.execute(game_query)
        if not game_result.scalar_one_or_none():
            return None

        query = select(GameStateDB).where(GameStateDB.game_id == game_id)  # type: ignore

        if turn is not None:
            query = query.where(GameStateDB.turn_number == turn)  # type: ignore
        else:
            query = query.order_by(GameStateDB.turn_number.desc()).limit(1)  # type: ignore

        result = await session.execute(query)
        state_record = result.scalar_one_or_none()

        if state_record:
            # For now, return the raw data since GameState reconstruction from JSON
            # requires complex enum deserialization. In practice, we'd rebuild the
            # GameState from the raw data with proper enum conversion.
            return state_record.state_data  # type: ignore
        return None

    @staticmethod
    async def update_game_status(
        session: AsyncSession,
        game_id: str,
        status: GameStatus,
        current_turn: int | None = None,
    ) -> None:
        """Update game status and metadata."""
        values = {"status": status, "updated_at": datetime.now(UTC)}
        if current_turn is not None:
            values["current_turn"] = current_turn

        await session.execute(update(Game).where(Game.id == game_id).values(**values))  # type: ignore
        await session.commit()

    @staticmethod
    async def soft_delete_game(session: AsyncSession, game_id: str) -> bool:
        """Soft delete a game by setting deleted_at timestamp."""
        result = await session.execute(
            update(Game)
            .where(and_(Game.id == game_id, Game.deleted_at == None))  # type: ignore
            .values(
                deleted_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        await session.commit()
        return result.rowcount > 0

    @staticmethod
    async def restore_game(session: AsyncSession, game_id: str) -> bool:
        """Restore a soft-deleted game by clearing deleted_at."""
        result = await session.execute(
            update(Game)
            .where(and_(Game.id == game_id, Game.deleted_at != None))  # type: ignore
            .values(deleted_at=None, updated_at=datetime.now(UTC))
        )
        await session.commit()
        return result.rowcount > 0

    @staticmethod
    async def list_active_games(session: AsyncSession) -> list[Game]:
        """List all non-deleted games."""
        query = (
            select(Game)
            .where(Game.deleted_at.is_(None))  # type: ignore
            .order_by(Game.created_at.desc())  # type: ignore
        )
        result = await session.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def list_deleted_games(session: AsyncSession) -> list[Game]:
        """List all soft-deleted games."""
        query = (
            select(Game)
            .where(Game.deleted_at.is_not(None))  # type: ignore
            .order_by(Game.deleted_at.desc())  # type: ignore
        )
        result = await session.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def record_action(
        session: AsyncSession,
        game_id: str,
        turn: int,
        player_id: str,
        action_type: Any,
        action_data: dict[str, Any],
    ) -> str:
        """Record an action attempt."""
        action_id = str(uuid.uuid4())

        # Convert enum to string if needed
        action_type_str = action_type.value if hasattr(action_type, 'value') else str(action_type)
        
        action = Action(
            id=action_id,
            game_id=game_id,
            turn_number=turn,
            player_id=player_id,
            action_type=action_type_str,
            action_data=action_data,
            is_valid=None,  # Processing state
            created_at=datetime.now(UTC),
        )

        session.add(action)
        await session.commit()
        return action_id

    @staticmethod
    async def complete_action(
        session: AsyncSession,
        action_id: str,
        is_valid: bool,
        error_message: str | None = None,
        processing_time_ms: int | None = None,
    ) -> None:
        """Complete action processing with result."""
        await session.execute(
            update(Action)  # type: ignore
            .where(Action.id == action_id)  # type: ignore
            .values(
                is_valid=is_valid,
                error_message=error_message,
                processing_time_ms=processing_time_ms,
            )
        )
        await session.commit()

    @staticmethod
    async def record_event(
        session: AsyncSession,
        game_id: str,
        turn: int,
        event_type: str,
        player_id: str | None,
        event_data: dict[str, Any],
    ) -> str:
        """Record a game event."""
        event_id = str(uuid.uuid4())

        event = Event(
            id=event_id,
            game_id=game_id,
            turn_number=turn,
            event_type=event_type,
            player_id=player_id,
            event_data=event_data,
            created_at=datetime.now(UTC),
        )

        session.add(event)
        await session.commit()
        return event_id

    @staticmethod
    async def record_chat_message(
        session: AsyncSession,
        game_id: str,
        turn: int,
        speaker_id: str,
        message: str,
        phase: str,
    ) -> str:
        """Record a chat message."""
        message_id = str(uuid.uuid4())

        chat_message = ChatMessage(
            id=message_id,
            game_id=game_id,
            turn_number=turn,
            speaker_id=speaker_id,
            message=message,
            phase=phase,
            created_at=datetime.now(UTC),
        )

        session.add(chat_message)
        await session.commit()
        return message_id

    @staticmethod
    async def record_agent_metrics(
        session: AsyncSession,
        game_id: str,
        player_id: str,
        turn: int,
        tokens_used: int | None = None,
        response_time_ms: int | None = None,
        invalid_attempts: int = 0,
        internal_state_size: int | None = None,
        memory_usage_mb: float | None = None,
    ) -> str:
        """Record agent performance metrics."""
        metric_id = str(uuid.uuid4())

        metric = AgentMetric(
            id=metric_id,
            game_id=game_id,
            player_id=player_id,
            turn_number=turn,
            tokens_used=tokens_used,
            response_time_ms=response_time_ms,
            invalid_attempts=invalid_attempts,
            internal_state_size=internal_state_size,
            memory_usage_mb=memory_usage_mb,
            created_at=datetime.now(UTC),
        )

        session.add(metric)
        await session.commit()
        return metric_id


class RecoveryOperations:
    """Database operations for game recovery."""

    @staticmethod
    async def find_interrupted_games(session: AsyncSession) -> list[str]:
        """Find games that were interrupted and need recovery."""
        # Find active games with incomplete actions
        query = (
            select(Game)  # type: ignore
            .where(Game.status == GameStatus.ACTIVE)  # type: ignore
            .where(
                exists(
                    select(1).where(
                        and_(Action.game_id == Game.id, Action.is_valid.is_(None))  # type: ignore
                    )
                )
            )
        )

        result = await session.execute(query)
        games = result.scalars().all()
        return [game.id for game in games]

    @staticmethod
    async def analyze_failure_type(
        session: AsyncSession, game_id: str
    ) -> dict[str, Any]:
        """Analyze the type of failure for recovery strategy."""
        # Get last complete state
        last_state_query = (
            select(GameStateDB.turn_number)  # type: ignore
            .where(GameStateDB.game_id == game_id)  # type: ignore
            .order_by(GameStateDB.turn_number.desc())  # type: ignore
            .limit(1)
        )

        last_state_result = await session.execute(last_state_query)
        last_turn = last_state_result.scalar_one_or_none()

        # Get incomplete actions
        incomplete_actions_query = (
            select(Action)
            .where(and_(Action.game_id == game_id, Action.is_valid.is_(None)))  # type: ignore
            .order_by(Action.created_at)
        )

        incomplete_result = await session.execute(incomplete_actions_query)
        incomplete_actions = incomplete_result.fetchall()

        # Determine failure type
        if incomplete_actions:
            recovery_type = RecoveryType.INCOMPLETE_ACTION
        elif last_turn is None:
            recovery_type = RecoveryType.TRANSACTION_FAILURE
        else:
            recovery_type = RecoveryType.AGENT_TIMEOUT

        return {
            "type": recovery_type,
            "last_valid_turn": last_turn or 0,
            "incomplete_actions": [action.id for action in incomplete_actions],
            "incomplete_count": len(incomplete_actions),
        }

    @staticmethod
    async def mark_incomplete_actions_failed(
        session: AsyncSession,
        game_id: str,
        recovery_message: str = "Process interrupted",
    ) -> int:
        """Mark all incomplete actions for a game as failed."""
        result = await session.execute(
            update(Action)
            .where(and_(Action.game_id == game_id, Action.is_valid.is_(None)))  # type: ignore
            .values(is_valid=False, error_message=recovery_message)
        )
        await session.commit()
        return result.rowcount

    @staticmethod
    async def get_last_consistent_state(
        session: AsyncSession, game_id: str
    ) -> tuple[int, dict[str, Any]] | None:
        """Get the last game state that has complete corresponding actions and events."""
        # Find the highest turn number with both state and valid actions
        query = (
            select(GameStateDB.turn_number, GameStateDB.state_data)  # type: ignore
            .where(GameStateDB.game_id == game_id)  # type: ignore
            .where(
                exists(
                    select(1).where(  # type: ignore
                        and_(
                            Action.game_id == game_id,
                            Action.turn_number == GameStateDB.turn_number,
                            Action.is_valid,
                        )
                    )
                )
            )
            .order_by(GameStateDB.turn_number.desc())  # type: ignore
            .limit(1)
        )

        result = await session.execute(query)
        row = result.fetchone()

        if row:
            turn_number, state_data = row
            # Return raw state data for reconstruction by the game engine
            return turn_number, state_data

        return None


class AnalyticsOperations:
    """Database operations for game analysis and metrics."""

    @staticmethod
    async def get_agent_performance(
        session: AsyncSession, game_id: str
    ) -> dict[str, Any]:
        """Get agent performance metrics for a game."""
        query = (
            select(  # type: ignore
                AgentMetric.player_id,
                func.avg(AgentMetric.response_time_ms).label("avg_response_time"),
                func.sum(AgentMetric.invalid_attempts).label("total_invalid_attempts"),
                func.avg(AgentMetric.tokens_used).label("avg_tokens"),
                func.count().label("action_count"),
            )
            .where(AgentMetric.game_id == game_id)  # type: ignore
            .group_by(AgentMetric.player_id)  # type: ignore
        )

        result = await session.execute(query)
        return {
            row.player_id: {
                "avg_response_time": row.avg_response_time,
                "total_invalid_attempts": row.total_invalid_attempts or 0,
                "avg_tokens": row.avg_tokens,
                "action_count": row.action_count,
            }
            for row in result
        }

    @staticmethod
    async def get_game_timeline(
        session: AsyncSession, game_id: str
    ) -> list[dict[str, Any]]:
        """Get complete timeline of actions and events for a game."""
        # Get actions
        actions_query = (
            select(Action)  # type: ignore
            .where(Action.game_id == game_id)  # type: ignore
            .order_by(Action.turn_number, Action.created_at)  # type: ignore
        )
        actions_result = await session.execute(actions_query)
        actions = actions_result.scalars().all()

        # Get events
        events_query = (
            select(Event)  # type: ignore
            .where(Event.game_id == game_id)  # type: ignore
            .order_by(Event.turn_number, Event.created_at)  # type: ignore
        )
        events_result = await session.execute(events_query)
        events = events_result.scalars().all()

        # Combine timeline
        timeline = []

        for action in actions:
            timeline.append(
                {
                    "type": "action",
                    "turn": action.turn_number,
                    "timestamp": action.created_at,
                    "player_id": action.player_id,
                    "action_type": action.action_type,
                    "data": action.action_data,
                    "is_valid": action.is_valid,
                    "error": action.error_message,
                }
            )

        for event in events:
            timeline.append(
                {
                    "type": "event",
                    "turn": event.turn_number,
                    "timestamp": event.created_at,
                    "player_id": event.player_id,
                    "event_type": event.event_type,
                    "data": event.event_data,
                }
            )

        # Sort by turn and timestamp
        timeline.sort(key=lambda x: (x["turn"], x["timestamp"]))
        return timeline
