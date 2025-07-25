"""Unit of Work pattern implementation for atomic database operations.

This module provides transaction management to ensure atomicity across
multiple database operations. A single game action can result in multiple
database writes (state change, action log, event creation), and this pattern
ensures either all succeed or all are rolled back.
"""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from .connection import get_async_session
from .models import (
    Action,
    AgentMetric,
    ChatMessage,
    Event,
    Game,
    GameStateDB,
    PlayerDB,
)

logger = logging.getLogger(__name__)


class UnitOfWork:
    """
    Unit of Work pattern implementation for atomic database operations.

    This class manages a database session and provides methods to perform
    multiple operations atomically. If any operation fails, all changes
    are rolled back automatically.

    Usage:
        async with UnitOfWork() as uow:
            await uow.save_game_state(game_id, state)
            await uow.record_action(action_data)
            await uow.log_event(event_data)
            # All operations committed together at context exit
    """

    def __init__(self, session: AsyncSession | None = None):
        """Initialize Unit of Work with optional existing session."""
        self._session = session
        self._should_close_session = session is None
        self._committed = False

    async def __aenter__(self) -> "UnitOfWork":
        """Enter async context and initialize session if needed."""
        if self._session is None:
            async_session_gen = get_async_session()
            self._session = await async_session_gen.__anext__()  # type: ignore[attr-defined]
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit async context, handling commit/rollback and session cleanup."""
        try:
            if exc_type is None and not self._committed:
                # No exception occurred, commit the transaction
                await self._session.commit()  # type: ignore[union-attr]
                self._committed = True
                logger.debug("Transaction committed successfully")
            else:
                # Exception occurred or already committed, rollback
                await self._session.rollback()  # type: ignore[union-attr]
                if exc_type is not None:
                    logger.warning(
                        f"Transaction rolled back due to exception: {exc_val}"
                    )
        except Exception as cleanup_error:
            logger.error(f"Error during transaction cleanup: {cleanup_error}")
            # Re-raise the original exception if there was one
            if exc_type is not None:
                raise exc_val from cleanup_error
            raise cleanup_error
        finally:
            if self._should_close_session and self._session:
                await self._session.close()

    async def commit(self) -> None:
        """Explicitly commit the transaction."""
        if self._session and not self._committed:
            await self._session.commit()
            self._committed = True
            logger.debug("Transaction explicitly committed")

    async def rollback(self) -> None:
        """Explicitly rollback the transaction."""
        if self._session:
            await self._session.rollback()
            logger.debug("Transaction explicitly rolled back")

    # Game operations
    async def create_game(self, game: Game) -> Game:
        """Create a new game record."""
        self._session.add(game)  # type: ignore
        await self._session.flush()  # type: ignore
        await self._session.refresh(game)  # type: ignore
        return game

    async def get_game(self, game_id: UUID) -> Game | None:
        """Get a game by ID."""
        result = await self._session.execute(select(Game).where(Game.id == game_id))  # type: ignore
        return result.scalar_one_or_none()

    async def update_game_status(
        self, game_id: UUID, status: str, winner: str | None = None
    ) -> None:
        """Update game status and winner."""
        result = await self._session.execute(select(Game).where(Game.id == game_id))  # type: ignore
        game = result.scalar_one_or_none()
        if game:
            game.status = status
            if winner is not None:
                game.winner = winner
            self._session.add(game)  # type: ignore

    # Player operations
    async def create_players(self, players: list[PlayerDB]) -> list[PlayerDB]:
        """Create multiple player records."""
        for player in players:
            self._session.add(player)  # type: ignore
        await self._session.flush()  # type: ignore
        for player in players:
            await self._session.refresh(player)  # type: ignore
        return players

    # Game state operations
    async def save_game_state(self, game_state: GameStateDB) -> GameStateDB:
        """Save a game state snapshot."""
        self._session.add(game_state)  # type: ignore
        await self._session.flush()  # type: ignore
        await self._session.refresh(game_state)  # type: ignore
        return game_state

    async def get_latest_game_state(self, game_id: UUID) -> GameStateDB | None:
        """Get the latest game state for a game."""
        result = await self._session.execute(  # type: ignore[union-attr]
            select(GameStateDB)
            .where(GameStateDB.game_id == game_id)
            .order_by(GameStateDB.turn_number.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    # Action operations
    async def record_action(self, action: Action) -> Action:
        """Record a player action."""
        self._session.add(action)  # type: ignore
        await self._session.flush()  # type: ignore
        await self._session.refresh(action)  # type: ignore
        return action

    async def complete_action(
        self, action_id: UUID, success: bool, error_message: str | None = None
    ) -> None:
        """Mark an action as completed."""
        result = await self._session.execute(  # type: ignore[union-attr]
            select(Action).where(Action.id == action_id)
        )
        action = result.scalar_one_or_none()
        if action:
            action.completed = True
            action.success = success
            if error_message:
                action.error_message = error_message
            self._session.add(action)  # type: ignore

    # Event operations
    async def log_event(self, event: Event) -> Event:
        """Log a game event."""
        self._session.add(event)  # type: ignore
        await self._session.flush()  # type: ignore
        await self._session.refresh(event)  # type: ignore
        return event

    async def log_events(self, events: list[Event]) -> list[Event]:
        """Log multiple game events."""
        for event in events:
            self._session.add(event)  # type: ignore
        await self._session.flush()  # type: ignore
        for event in events:
            await self._session.refresh(event)  # type: ignore
        return events

    # Chat operations
    async def save_chat_message(self, message: ChatMessage) -> ChatMessage:
        """Save a chat message."""
        self._session.add(message)  # type: ignore
        await self._session.flush()  # type: ignore
        await self._session.refresh(message)  # type: ignore
        return message

    # Metrics operations
    async def record_agent_metrics(self, metrics: AgentMetric) -> AgentMetric:
        """Record agent performance metrics."""
        self._session.add(metrics)  # type: ignore
        await self._session.flush()  # type: ignore
        await self._session.refresh(metrics)  # type: ignore
        return metrics


@asynccontextmanager
async def unit_of_work(
    session: AsyncSession | None = None,
) -> AsyncGenerator[UnitOfWork]:
    """
    Context manager for creating a Unit of Work.

    This is a convenience function that can be used directly without
    instantiating the UnitOfWork class.

    Usage:
        async with unit_of_work() as uow:
            await uow.save_game_state(game_id, state)
            await uow.record_action(action_data)
            # All operations committed atomically
    """
    async with UnitOfWork(session) as uow:
        yield uow


class GameActionTransaction:
    """
    High-level transaction wrapper for complete game actions.

    This class provides a simplified interface for the most common
    transaction pattern: performing a game action that results in
    state changes, action logging, and event creation.
    """

    def __init__(self, uow: UnitOfWork):
        """Initialize with an existing Unit of Work."""
        self.uow = uow
        self.action_id: UUID | None = None

    async def begin_action(self, action: Action) -> UUID:
        """Begin recording a new action."""
        recorded_action = await self.uow.record_action(action)
        self.action_id = recorded_action.id  # type: ignore[assignment]
        return self.action_id  # type: ignore[return-value]

    async def save_state_and_events(
        self, game_state: GameStateDB, events: list[Event]
    ) -> None:
        """Save the new game state and associated events."""
        await self.uow.save_game_state(game_state)
        if events:
            await self.uow.log_events(events)

    async def complete_action_success(self) -> None:
        """Mark the current action as successfully completed."""
        if self.action_id:
            await self.uow.complete_action(self.action_id, success=True)

    async def complete_action_failure(self, error_message: str) -> None:
        """Mark the current action as failed with error message."""
        if self.action_id:
            await self.uow.complete_action(
                self.action_id, success=False, error_message=error_message
            )


@asynccontextmanager
async def game_action_transaction() -> AsyncGenerator[GameActionTransaction]:
    """
    Context manager for complete game action transactions.

    This provides the highest-level interface for game actions,
    automatically handling the Unit of Work lifecycle and providing
    convenient methods for the most common operations.

    Usage:
        async with game_action_transaction() as tx:
            action_id = await tx.begin_action(action_record)
            # ... perform game logic ...
            await tx.save_state_and_events(new_state, events)
            await tx.complete_action_success()
    """
    async with unit_of_work() as uow:
        yield GameActionTransaction(uow)
