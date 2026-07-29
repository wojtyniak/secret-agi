"""
Tests for the database layer: session management, action/event retrieval,
and persistence across connections.
"""

import tempfile
from pathlib import Path

import pytest

from secret_agi.database.connection import get_async_session, init_database
from secret_agi.database.models import Action, Event, Game
from secret_agi.database.operations import GameOperations


class TestAsyncSessionParameterError:
    """Test the get_async_session parameter error we found."""

    @pytest.mark.asyncio
    async def test_get_async_session_no_parameters(self):
        """Test that get_async_session() works without parameters."""
        # Initialize with in-memory database
        await init_database("sqlite+aiosqlite:///:memory:")

        # This should work (no parameters)
        async with get_async_session() as session:
            assert session is not None


class TestDatabaseOperations:
    """Test database operations that the game-log endpoint relies on."""

    @pytest.mark.asyncio
    async def test_get_actions_for_game(self):
        """Test GameOperations.get_actions_for_game method."""
        await init_database("sqlite+aiosqlite:///:memory:")

        # Create test data
        async with get_async_session() as session:
            game = Game(
                id="test-game",
                status="ACTIVE",
                config={"player_count": 5},
                current_turn=3
            )
            session.add(game)

            actions = [
                Action(
                    game_id="test-game",
                    player_id="player_1",
                    turn_number=1,
                    action_type="nominate",
                    action_data={"target_id": "player_2"},
                    is_valid=True
                ),
                Action(
                    game_id="test-game",
                    player_id="player_2",
                    turn_number=2,
                    action_type="vote_team",
                    action_data={"vote": True},
                    is_valid=True
                ),
                Action(
                    game_id="test-game",
                    player_id="player_3",
                    turn_number=3,
                    action_type="invalid_action",
                    action_data={},
                    is_valid=False,
                    error_message="Invalid action"
                )
            ]
            for action in actions:
                session.add(action)

            await session.commit()

        # Test retrieval
        async with get_async_session() as session:
            retrieved_actions = await GameOperations.get_actions_for_game(session, "test-game")

            assert len(retrieved_actions) == 3
            assert retrieved_actions[0].action_type == "nominate"
            assert retrieved_actions[0].is_valid is True
            assert retrieved_actions[1].action_type == "vote_team"
            assert retrieved_actions[2].action_type == "invalid_action"
            assert retrieved_actions[2].is_valid is False
            assert retrieved_actions[2].error_message == "Invalid action"

    @pytest.mark.asyncio
    async def test_get_events_for_game(self):
        """Test GameOperations.get_events_for_game method."""
        await init_database("sqlite+aiosqlite:///:memory:")

        # Create test data
        async with get_async_session() as session:
            game = Game(
                id="test-game",
                status="ACTIVE",
                config={"player_count": 5},
                current_turn=3
            )
            session.add(game)

            events = [
                Event(
                    game_id="test-game",
                    turn_number=1,
                    event_type="paper_published",
                    event_data={"paper": {"capability": 2, "safety": 1}},
                    player_id="player_1"
                ),
                Event(
                    game_id="test-game",
                    turn_number=3,
                    event_type="game_ended",
                    event_data={"winners": ["Safety"]},
                    player_id=None
                )
            ]
            for event in events:
                session.add(event)

            await session.commit()

        # Test retrieval
        async with get_async_session() as session:
            retrieved_events = await GameOperations.get_events_for_game(session, "test-game")

            assert len(retrieved_events) == 2
            assert retrieved_events[0].event_type == "paper_published"
            assert retrieved_events[0].event_data["paper"]["capability"] == 2
            assert retrieved_events[1].event_type == "game_ended"
            assert retrieved_events[1].event_data["winners"] == ["Safety"]


class TestDatabasePersistence:
    """Test database persistence scenarios that caused issues."""

    @pytest.mark.asyncio
    async def test_database_persistence_across_connections(self):
        """Test that data persists across different database connections."""
        # Create temporary database file
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        db_url = f"sqlite+aiosqlite:///{db_path}"

        try:
            # Initialize database
            await init_database(db_url)

            # Create data with first connection
            async with get_async_session() as session:
                game = Game(
                    id="persist-test",
                    status="COMPLETED",
                    config={"player_count": 5},
                    current_turn=10
                )
                session.add(game)
                await session.commit()

            # Verify data persists with new connection
            # (Simulating server restart scenario)
            await init_database(db_url)  # Re-initialize

            async with get_async_session() as session:
                # This is the pattern used in the fixed API
                from sqlalchemy import text
                result = await session.execute(
                    text("SELECT id FROM games ORDER BY created_at DESC LIMIT 1")
                )
                row = result.fetchone()

                assert row is not None
                assert row[0] == "persist-test"

        finally:
            # Cleanup
            Path(db_path).unlink(missing_ok=True)

class TestErrorConditions:
    """Test various error conditions found during development."""

    @pytest.mark.asyncio
    async def test_database_connection_with_nonexistent_table(self):
        """Test database error handling with non-existent tables."""
        await init_database("sqlite+aiosqlite:///:memory:")

        async with get_async_session() as session:
            # This should not crash, but may return empty results
            try:
                from sqlalchemy import text
                result = await session.execute(text("SELECT * FROM non_existent_table"))
                # If we get here, the table exists (unexpected)
                rows = result.fetchall()
                assert len(rows) == 0
            except Exception as e:
                # Expected behavior - table doesn't exist
                assert "no such table" in str(e).lower() or "doesn't exist" in str(e).lower()
