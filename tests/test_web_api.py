"""
Tests for the web API game-log endpoint and database persistence.

This test suite covers the errors found during web interface testing:
1. get_async_session() parameter error
2. Game log fallback behavior when orchestrator state is lost
3. Database persistence across server restarts
4. SimpleOrchestrator property access
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from secret_agi.api.simple_api import app, current_game, current_orchestrator, game_log
from secret_agi.database.connection import get_async_session, init_database
from secret_agi.database.models import Action, Event, Game
from secret_agi.database.operations import GameOperations
from secret_agi.orchestrator.simple_orchestrator import SimpleOrchestrator
from secret_agi.players.random_player import RandomPlayer


class TestWebAPIGameLog:
    """Test the game-log endpoint and related functionality."""

    @pytest.fixture
    def client(self):
        """Create a test client for the FastAPI app."""
        return TestClient(app)

    @pytest.fixture
    async def temp_db_url(self):
        """Create a temporary database URL for testing."""
        # Use a temporary file for testing
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        db_url = f"sqlite+aiosqlite:///{db_path}"

        # Initialize the test database
        await init_database(db_url)

        yield db_url

        # Cleanup
        Path(db_path).unlink(missing_ok=True)

    @pytest.fixture
    async def sample_game_data(self, temp_db_url):
        """Create sample game data in the database."""
        async with get_async_session() as session:
            # Create a game
            game = Game(
                id="test-game-123",
                status="COMPLETED",
                config={"player_count": 5},
                current_turn=10,
                final_outcome={"winners": ["Safety"]},
                game_metadata={"test": True}
            )
            session.add(game)

            # Create some actions
            actions = [
                Action(
                    game_id="test-game-123",
                    player_id="player_1",
                    turn_number=1,
                    action_type="nominate",
                    action_data={"target_id": "player_2"},
                    is_valid=True,
                    error_message=None
                ),
                Action(
                    game_id="test-game-123",
                    player_id="player_2",
                    turn_number=2,
                    action_type="vote_team",
                    action_data={"vote": True},
                    is_valid=True,
                    error_message=None
                ),
                Action(
                    game_id="test-game-123",
                    player_id="player_3",
                    turn_number=3,
                    action_type="invalid_action",
                    action_data={},
                    is_valid=False,
                    error_message="Invalid action type"
                )
            ]
            for action in actions:
                session.add(action)

            # Create some events
            events = [
                Event(
                    game_id="test-game-123",
                    turn_number=2,
                    event_type="paper_published",
                    event_data={"paper": {"capability": 2, "safety": 1}},
                    player_id="player_2"
                ),
                Event(
                    game_id="test-game-123",
                    turn_number=5,
                    event_type="game_ended",
                    event_data={"winners": ["Safety"]},
                    player_id=None
                )
            ]
            for event in events:
                session.add(event)

            await session.commit()

        return "test-game-123"

    def test_game_log_endpoint_exists(self, client):
        """Test that the game-log endpoint exists and returns a response."""
        response = client.get("/game-log")
        assert response.status_code == 200
        data = response.json()
        assert "success" in data
        assert "message" in data
        assert "data" in data

    def test_game_log_fallback_behavior(self, client):
        """Test game-log endpoint when no game state is available."""
        # Clear global state to simulate server restart
        global current_game, current_orchestrator, game_log
        original_game = current_game.copy() if current_game else {}
        original_orchestrator = current_orchestrator
        original_log = game_log.copy() if game_log else []

        try:
            # Reset global state
            current_game.clear()
            current_orchestrator = None
            game_log.clear()

            response = client.get("/game-log")
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert "fallback" in data["message"].lower()
            assert isinstance(data["data"], list)

        finally:
            # Restore original state
            current_game.update(original_game)
            current_orchestrator = original_orchestrator
            game_log.clear()
            game_log.extend(original_log)

    @pytest.mark.asyncio
    async def test_game_operations_get_actions_for_game(self, sample_game_data):
        """Test GameOperations.get_actions_for_game method."""
        game_id = sample_game_data

        async with get_async_session() as session:
            actions = await GameOperations.get_actions_for_game(session, game_id)

            assert len(actions) == 3
            assert actions[0].action_type == "nominate"
            assert actions[0].is_valid is True
            assert actions[1].action_type == "vote_team"
            assert actions[2].action_type == "invalid_action"
            assert actions[2].is_valid is False
            assert actions[2].error_message == "Invalid action type"

    @pytest.mark.asyncio
    async def test_game_operations_get_events_for_game(self, sample_game_data):
        """Test GameOperations.get_events_for_game method."""
        game_id = sample_game_data

        async with get_async_session() as session:
            events = await GameOperations.get_events_for_game(session, game_id)

            assert len(events) == 2
            assert events[0].event_type == "paper_published"
            assert events[0].event_data["paper"]["capability"] == 2
            assert events[1].event_type == "game_ended"
            assert events[1].event_data["winners"] == ["Safety"]

    @pytest.mark.asyncio
    async def test_get_async_session_parameter_error(self):
        """Test that get_async_session() doesn't accept parameters."""
        # This should work (no parameters)
        async with get_async_session() as session:
            assert isinstance(session, AsyncSession)

        # This should fail (with parameters) - documenting the error we found
        with pytest.raises(TypeError, match="takes 0 positional arguments but 1 was given"):
            async with get_async_session("sqlite:///test.db") as session:
                pass

    def test_game_log_action_formatting(self, client):
        """Test that action entries are properly formatted in the game log."""
        # Mock database response with sample actions
        with patch('secret_agi.api.simple_api.GameOperations.get_actions_for_game') as mock_get_actions:
            with patch('secret_agi.api.simple_api.GameOperations.get_events_for_game') as mock_get_events:
                with patch('secret_agi.api.simple_api.get_async_session'):

                    # Mock sample actions
                    mock_action_1 = MagicMock()
                    mock_action_1.turn_number = 1
                    mock_action_1.player_id = "player_1"
                    mock_action_1.action_type = "nominate"
                    mock_action_1.action_data = {"target_id": "player_2"}
                    mock_action_1.is_valid = True
                    mock_action_1.error_message = None

                    mock_action_2 = MagicMock()
                    mock_action_2.turn_number = 2
                    mock_action_2.player_id = "player_3"
                    mock_action_2.action_type = "vote_team"
                    mock_action_2.action_data = {"vote": False}
                    mock_action_2.is_valid = True
                    mock_action_2.error_message = None

                    mock_get_actions.return_value = [mock_action_1, mock_action_2]
                    mock_get_events.return_value = []

                    # Mock current_game to have a game_id
                    with patch('secret_agi.api.simple_api.current_game', {"game_id": "test-123"}):
                        response = client.get("/game-log")

                    assert response.status_code == 200
                    data = response.json()
                    assert data["success"] is True

                    # Check that actions are properly formatted
                    log_entries = data["data"]
                    action_entries = [entry for entry in log_entries if entry.get("type") == "action"]

                    assert len(action_entries) >= 2

                    # Check nominate action formatting
                    nominate_entry = next((e for e in action_entries if "nominate" in e["message"]), None)
                    assert nominate_entry is not None
                    assert "target: player_2" in nominate_entry["message"]
                    assert "✅" in nominate_entry["message"]

                    # Check vote action formatting
                    vote_entry = next((e for e in action_entries if "vote_team" in e["message"]), None)
                    assert vote_entry is not None
                    assert "NO" in vote_entry["message"]  # vote: False should show as NO


class TestSimpleOrchestratorProperties:
    """Test SimpleOrchestrator properties that were added to fix game-log access."""

    @pytest.fixture
    def orchestrator(self):
        """Create a test orchestrator."""
        return SimpleOrchestrator(database_url="sqlite:///:memory:", debug_mode=True)

    def test_current_game_id_property_initially_none(self, orchestrator):
        """Test that current_game_id is None initially."""
        assert orchestrator.current_game_id is None

    def test_engine_property_initially_none(self, orchestrator):
        """Test that engine property is None initially."""
        assert orchestrator.engine is None

    @pytest.mark.asyncio
    async def test_current_game_id_after_game_run(self, orchestrator):
        """Test that current_game_id is set after running a game."""
        players = [
            RandomPlayer("player_1"),
            RandomPlayer("player_2"),
            RandomPlayer("player_3"),
            RandomPlayer("player_4"),
            RandomPlayer("player_5"),
        ]

        result = await orchestrator.run_game(players)

        # After running a game, current_game_id should be set
        assert orchestrator.current_game_id is not None
        assert orchestrator.current_game_id == result["game_id"]

    @pytest.mark.asyncio
    async def test_engine_property_after_game_run(self, orchestrator):
        """Test that engine property is available after running a game."""
        players = [
            RandomPlayer("player_1"),
            RandomPlayer("player_2"),
            RandomPlayer("player_3"),
            RandomPlayer("player_4"),
            RandomPlayer("player_5"),
        ]

        await orchestrator.run_game(players)

        # After running a game, engine should be available
        assert orchestrator.engine is not None
        assert hasattr(orchestrator.engine, "_engine")  # Internal SQLAlchemy engine


class TestDatabasePersistenceAcrossRestarts:
    """Test database persistence when server state is lost."""

    @pytest.mark.asyncio
    async def test_database_persistence_with_file_db(self):
        """Test that game data persists in file database across orchestrator instances."""
        # Create temporary database file
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        db_url = f"sqlite+aiosqlite:///{db_path}"

        try:
            # First orchestrator - create and run a game
            orchestrator1 = SimpleOrchestrator(database_url=db_url, debug_mode=False)
            players = [RandomPlayer(f"player_{i}") for i in range(5)]

            result1 = await orchestrator1.run_game(players)
            game_id = result1["game_id"]

            # Verify data was written
            async with get_async_session() as session:
                actions = await GameOperations.get_actions_for_game(session, game_id)
                assert len(actions) > 0  # Should have some actions

            # Simulate server restart - create new orchestrator instance
            SimpleOrchestrator(database_url=db_url, debug_mode=False)

            # Verify data persists across orchestrator instances
            async with get_async_session() as session:
                actions = await GameOperations.get_actions_for_game(session, game_id)
                events = await GameOperations.get_events_for_game(session, game_id)

                assert len(actions) > 0
                # Should have at least one game_ended event
                game_end_events = [e for e in events if e.event_type == "game_ended"]
                assert len(game_end_events) > 0

        finally:
            # Cleanup
            Path(db_path).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_most_recent_game_query(self):
        """Test querying for the most recent game from database."""
        # Create temporary database
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        db_url = f"sqlite+aiosqlite:///{db_path}"

        try:
            await init_database(db_url)

            # Create multiple games with different timestamps
            async with get_async_session() as session:
                import time

                game1 = Game(
                    id="game-1",
                    status="COMPLETED",
                    config={"player_count": 5},
                    current_turn=10
                )
                session.add(game1)
                await session.commit()

                # Small delay to ensure different timestamps
                time.sleep(0.01)

                game2 = Game(
                    id="game-2",
                    status="COMPLETED",
                    config={"player_count": 5},
                    current_turn=15
                )
                session.add(game2)
                await session.commit()

                # Query most recent game
                from sqlalchemy import text
                result = await session.execute(
                    text("SELECT id FROM games ORDER BY created_at DESC LIMIT 1")
                )
                row = result.fetchone()

                assert row is not None
                assert row[0] == "game-2"  # Most recent game

        finally:
            Path(db_path).unlink(missing_ok=True)


class TestErrorConditions:
    """Test various error conditions found during development."""

    def test_game_log_with_empty_current_game(self, client):
        """Test game-log endpoint behavior with empty current_game dict."""
        global current_game
        original_game = current_game.copy() if current_game else {}

        try:
            current_game.clear()  # Empty but not None

            response = client.get("/game-log")
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True

        finally:
            current_game.update(original_game)

    def test_game_log_with_none_orchestrator(self, client):
        """Test game-log endpoint behavior with None orchestrator."""
        global current_orchestrator
        original_orchestrator = current_orchestrator

        try:
            current_orchestrator = None

            response = client.get("/game-log")
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True

        finally:
            current_orchestrator = original_orchestrator

    @pytest.mark.asyncio
    async def test_database_connection_error_handling(self):
        """Test handling of database connection errors."""
        # Try to access non-existent database
        from sqlalchemy import text
        with pytest.raises((Exception, OSError)):  # Should raise some database error
            async with get_async_session() as session:
                await session.execute(text("SELECT * FROM non_existent_table"))

    def test_action_data_none_handling(self, client):
        """Test that action formatting handles None action_data gracefully."""
        with patch('secret_agi.api.simple_api.GameOperations.get_actions_for_game') as mock_get_actions:
            with patch('secret_agi.api.simple_api.GameOperations.get_events_for_game') as mock_get_events:
                with patch('secret_agi.api.simple_api.get_async_session'):

                    # Mock action with None action_data
                    mock_action = MagicMock()
                    mock_action.turn_number = 1
                    mock_action.player_id = "player_1"
                    mock_action.action_type = "observe"
                    mock_action.action_data = None  # This was causing issues
                    mock_action.is_valid = True
                    mock_action.error_message = None

                    mock_get_actions.return_value = [mock_action]
                    mock_get_events.return_value = []

                    with patch('secret_agi.api.simple_api.current_game', {"game_id": "test-123"}):
                        response = client.get("/game-log")

                    assert response.status_code == 200
                    data = response.json()
                    assert data["success"] is True
                    # Should not crash with None action_data
