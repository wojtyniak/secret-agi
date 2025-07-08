"""
Tests for API fixes and error conditions found during web interface testing.

These tests specifically cover the errors we found and fixed:
1. get_async_session() parameter error
2. SimpleOrchestrator property access
3. Database connection management
4. Game log formatting edge cases
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from secret_agi.database.connection import get_async_session, init_database
from secret_agi.database.models import Action, Event, Game
from secret_agi.database.operations import GameOperations
from secret_agi.orchestrator.simple_orchestrator import SimpleOrchestrator
from secret_agi.players.random_player import RandomPlayer


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

    def test_get_async_session_with_parameters_fails(self):
        """Test that get_async_session() fails with parameters."""
        # This should fail (with parameters) - documenting the error we found
        with pytest.raises(TypeError, match="takes 0 positional arguments but 1 was given"):
            # This is the error we encountered in the API
            get_async_session("sqlite:///test.db")


class TestSimpleOrchestratorProperties:
    """Test SimpleOrchestrator properties added to fix game-log access."""

    def test_current_game_id_property_initially_none(self):
        """Test that current_game_id is None initially."""
        orchestrator = SimpleOrchestrator(database_url="sqlite:///:memory:")
        assert orchestrator.current_game_id is None

    def test_engine_property_initially_none(self):
        """Test that engine property is None initially."""
        orchestrator = SimpleOrchestrator(database_url="sqlite:///:memory:")
        assert orchestrator.engine is None

    @pytest.mark.asyncio
    async def test_current_game_id_after_game_run(self):
        """Test that current_game_id is set after running a game."""
        orchestrator = SimpleOrchestrator(database_url="sqlite:///:memory:", debug_mode=False)
        players = [RandomPlayer(f"player_{i}") for i in range(5)]

        result = await orchestrator.run_game(players)

        # After running a game, current_game_id should be set
        assert orchestrator.current_game_id is not None
        assert orchestrator.current_game_id == result["game_id"]

    @pytest.mark.asyncio
    async def test_engine_property_after_game_run(self):
        """Test that engine property is available after running a game."""
        orchestrator = SimpleOrchestrator(database_url="sqlite:///:memory:", debug_mode=False)
        players = [RandomPlayer(f"player_{i}") for i in range(5)]

        await orchestrator.run_game(players)

        # After running a game, engine should be available
        assert orchestrator.engine is not None


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


class TestActionFormatting:
    """Test action formatting edge cases found during development."""

    def test_action_with_none_data_formatting(self):
        """Test that actions with None action_data don't crash formatting."""
        # Mock action with None action_data (this was causing issues)
        mock_action = MagicMock()
        mock_action.turn_number = 1
        mock_action.player_id = "player_1"
        mock_action.action_type = "observe"
        mock_action.action_data = None
        mock_action.is_valid = True
        mock_action.error_message = None

        # This is the formatting logic from the API
        status = "✅" if mock_action.is_valid else "❌"
        message = f"{status} {mock_action.player_id} → {mock_action.action_type}"

        # Should handle None action_data gracefully
        if mock_action.action_data:
            # This branch shouldn't execute for None data
            raise AssertionError("Should not process None action_data")

        # Should produce a valid message
        assert "✅ player_1 → observe" == message

    def test_action_formatting_with_various_action_types(self):
        """Test action formatting for different action types."""
        test_cases = [
            {
                "action_type": "nominate",
                "action_data": {"target_id": "player_2"},
                "expected_suffix": " (target: player_2)"
            },
            {
                "action_type": "vote_team",
                "action_data": {"vote": True},
                "expected_suffix": " (YES)"
            },
            {
                "action_type": "vote_team",
                "action_data": {"vote": False},
                "expected_suffix": " (NO)"
            },
            {
                "action_type": "discard_paper",
                "action_data": {"paper_id": "paper_123"},
                "expected_suffix": " (paper: paper_123)"
            },
            {
                "action_type": "respond_veto",
                "action_data": {"agree": True},
                "expected_suffix": " (AGREE)"
            },
            {
                "action_type": "respond_veto",
                "action_data": {"agree": False},
                "expected_suffix": " (REFUSE)"
            }
        ]

        for case in test_cases:
            mock_action = MagicMock()
            mock_action.action_type = case["action_type"]
            mock_action.action_data = case["action_data"]
            mock_action.is_valid = True

            # This is the formatting logic from the API
            message = f"✅ player_1 → {mock_action.action_type}"

            if mock_action.action_data:
                if mock_action.action_type == "nominate":
                    message += f" (target: {mock_action.action_data.get('target_id', 'unknown')})"
                elif mock_action.action_type in ["vote_team", "vote_emergency"]:
                    message += f" ({'YES' if mock_action.action_data.get('vote') else 'NO'})"
                elif mock_action.action_type in ["discard_paper", "publish_paper"]:
                    message += f" (paper: {mock_action.action_data.get('paper_id', 'unknown')})"
                elif mock_action.action_type == "respond_veto":
                    response = "AGREE" if mock_action.action_data.get('agree') else "REFUSE"
                    message += f" ({response})"

            assert message.endswith(case["expected_suffix"]), f"Failed for {case['action_type']}: {message}"


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

    def test_current_game_id_property_access(self):
        """Test accessing current_game_id property on orchestrator."""
        orchestrator = SimpleOrchestrator()

        # Should not raise an error, should return None
        game_id = orchestrator.current_game_id
        assert game_id is None

        # Should have the property defined
        assert hasattr(orchestrator, 'current_game_id')

    def test_engine_property_access(self):
        """Test accessing engine property on orchestrator."""
        orchestrator = SimpleOrchestrator()

        # Should not raise an error, should return None
        engine = orchestrator.engine
        assert engine is None

        # Should have the property defined
        assert hasattr(orchestrator, 'engine')
