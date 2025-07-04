"""Unit tests for the game engine."""

import pytest

from secret_agi.engine.game_engine import (
    GameEngine,
    create_game,
    run_random_game,
)
from secret_agi.engine.models import ActionType, GameConfig, Phase, Role


class TestGameEngine:
    """Test GameEngine class."""

    @pytest.mark.asyncio
    async def test_game_creation(self):
        """Test basic game creation."""
        engine = GameEngine(database_url="sqlite:///:memory:")
        await engine.init_database()
        player_ids = ["p1", "p2", "p3", "p4", "p5"]
        config = GameConfig(5, player_ids, seed=42)

        game_id = await engine.create_game(config)
        assert engine._current_state is not None

        assert game_id is not None
        assert engine._current_state is not None
        assert engine._current_state.game_id == game_id
        assert len(engine._current_state.players) == 5
        assert engine._current_state.current_phase == Phase.TEAM_PROPOSAL

        # Check deck is created and shuffled
        assert len(engine._current_state.deck) == 17

        # Check role distribution
        roles = [p.role for p in engine._current_state.players]
        assert roles.count(Role.SAFETY) == 3
        assert roles.count(Role.ACCELERATIONIST) == 1
        assert roles.count(Role.AGI) == 1

    @pytest.mark.asyncio
    async def test_game_creation_different_sizes(self):
        """Test game creation with different player counts."""
        engine = GameEngine(database_url="sqlite:///:memory:")
        await engine.init_database()

        for count in range(5, 11):
            player_ids = [f"p{i}" for i in range(count)]
            config = GameConfig(count, player_ids)

            await engine.create_game(config)
            assert engine._current_state is not None

            assert len(engine._current_state.players) == count

            # Check role distribution is correct
            roles = [p.role for p in engine._current_state.players]
            assert roles.count(Role.AGI) == 1  # Always exactly 1 AGI

    @pytest.mark.asyncio
    async def test_get_game_state(self):
        """Test getting game state."""
        engine = GameEngine(database_url="sqlite:///:memory:")

        await engine.init_database()

        config = GameConfig(5, ["p1", "p2", "p3", "p4", "p5"])
        await engine.create_game(config)
        assert engine._current_state is not None

        # Full state (no player filter)
        full_state = engine.get_game_state()
        assert full_state is not None
        assert len(full_state.players) == 5

        # Filtered state for player
        filtered_state = engine.get_game_state("p1")
        assert filtered_state is not None

        # State should be different (filtered) but have same basic info
        assert filtered_state.game_id == full_state.game_id
        assert filtered_state.turn_number == full_state.turn_number

    @pytest.mark.asyncio
    async def test_get_valid_actions(self):
        """Test getting valid actions for players."""
        engine = GameEngine(database_url="sqlite:///:memory:")

        await engine.init_database()

        config = GameConfig(5, ["p1", "p2", "p3", "p4", "p5"])
        await engine.create_game(config)
        assert engine._current_state is not None

        # Director should be able to nominate
        director_id = engine._current_state.current_director.id
        actions = engine.get_valid_actions(director_id)
        assert ActionType.OBSERVE in actions
        assert ActionType.NOMINATE in actions

        # Non-director should not be able to nominate initially
        non_director_ids = [
            p.id for p in engine._current_state.players if p.id != director_id
        ]
        actions = engine.get_valid_actions(non_director_ids[0])
        assert ActionType.OBSERVE in actions
        assert ActionType.NOMINATE not in actions

    @pytest.mark.asyncio
    async def test_perform_action(self):
        """Test performing actions."""
        engine = GameEngine(database_url="sqlite:///:memory:")

        await engine.init_database()

        config = GameConfig(5, ["p1", "p2", "p3", "p4", "p5"], seed=42)
        await engine.create_game(config)
        assert engine._current_state is not None

        director_id = engine._current_state.current_director.id

        # Valid action
        eligible_engineers = [
            p.id
            for p in engine._current_state.players
            if p.id != director_id and not p.was_last_engineer
        ]
        target_id = eligible_engineers[0]

        result = await engine.perform_action(
            director_id, ActionType.NOMINATE, target_id=target_id
        )

        assert result.success is True
        assert result.error is None
        assert len(result.events) > 0
        assert engine._current_state.nominated_engineer_id == target_id

        # Turn number should increment
        assert engine._current_state.turn_number == 1

        # Invalid action
        result = await engine.perform_action(
            director_id, ActionType.NOMINATE, target_id=target_id
        )
        assert result.success is False
        assert result.error is not None and "already nominated" in result.error

    @pytest.mark.asyncio
    async def test_no_active_game(self):
        """Test operations when no game is active."""
        engine = GameEngine(database_url="sqlite:///:memory:")
        await engine.init_database()

        assert engine.get_game_state() is None
        assert engine.get_valid_actions("p1") == []
        assert engine.is_game_over() is False
        assert engine.get_winners() == []

        result = await engine.perform_action("p1", ActionType.OBSERVE)
        assert result.success is False
        assert result.error is not None and "No active game" in result.error

    @pytest.mark.asyncio
    async def test_game_completion_tracking(self):
        """Test game completion status tracking."""
        engine = GameEngine(database_url="sqlite:///:memory:")

        await engine.init_database()

        config = GameConfig(5, ["p1", "p2", "p3", "p4", "p5"])
        await engine.create_game(config)
        assert engine._current_state is not None

        assert engine.is_game_over() is False
        assert engine.get_winners() == []

        # Manually set game over for testing
        engine._current_state.is_game_over = True
        engine._current_state.winners = [Role.SAFETY]

        assert engine.is_game_over() is True
        assert engine.get_winners() == [Role.SAFETY]

    @pytest.mark.asyncio
    async def test_get_public_info(self):
        """Test getting public information."""
        engine = GameEngine(database_url="sqlite:///:memory:")

        await engine.init_database()

        config = GameConfig(5, ["p1", "p2", "p3", "p4", "p5"])
        await engine.create_game(config)
        assert engine._current_state is not None

        public_info = engine.get_public_info()

        assert "game_id" in public_info
        assert "turn_number" in public_info
        assert "current_phase" in public_info
        assert "capability" in public_info
        assert "safety" in public_info
        assert "alive_players" in public_info
        assert public_info["player_count"] == 5

    @pytest.mark.asyncio
    async def test_get_events_for_player(self):
        """Test getting events for a specific player."""
        engine = GameEngine(database_url="sqlite:///:memory:")

        await engine.init_database()

        config = GameConfig(5, ["p1", "p2", "p3", "p4", "p5"])
        await engine.create_game(config)
        assert engine._current_state is not None

        director_id = engine._current_state.current_director.id
        eligible_engineers = [
            p.id
            for p in engine._current_state.players
            if p.id != director_id and not p.was_last_engineer
        ]

        # Perform an action to generate events
        await engine.perform_action(
            director_id, ActionType.NOMINATE, target_id=eligible_engineers[0]
        )

        # Get events for player
        events = engine.get_events_for_player(director_id, since_turn=0)
        assert len(events) > 0

    @pytest.mark.asyncio
    async def test_save_game(self):
        """Test game saving."""
        engine = GameEngine(database_url="sqlite:///:memory:")

        await engine.init_database()

        config = GameConfig(5, ["p1", "p2", "p3", "p4", "p5"])
        await engine.create_game(config)
        assert engine._current_state is not None

        save_id = await engine.save_game()
        assert save_id is not None
        assert isinstance(save_id, str)

    @pytest.mark.asyncio
    async def test_get_game_stats(self):
        """Test getting game statistics."""
        engine = GameEngine(database_url="sqlite:///:memory:")

        await engine.init_database()

        config = GameConfig(5, ["p1", "p2", "p3", "p4", "p5"])
        await engine.create_game(config)
        assert engine._current_state is not None

        stats = engine.get_game_stats()

        assert stats["player_count"] == 5
        assert stats["alive_player_count"] == 5
        assert stats["turn_number"] == 0
        assert stats["deck_size"] == 17
        assert stats["current_phase"] == "TeamProposal"
        assert stats["is_game_over"] is False


class TestGameSimulation:
    """Test game simulation functionality."""

    @pytest.mark.asyncio
    async def test_simulate_to_completion(self):
        """Test simulating a game to completion."""
        engine = GameEngine(database_url="sqlite:///:memory:")

        await engine.init_database()

        config = GameConfig(5, ["p1", "p2", "p3", "p4", "p5"], seed=42)
        await engine.create_game(config)
        assert engine._current_state is not None

        result = await engine.simulate_to_completion(max_turns=100)

        assert "completed" in result
        assert "turns_taken" in result
        assert "winners" in result
        assert "final_stats" in result

        # Game should complete within reasonable turns
        assert result["turns_taken"] < 100

        if result["completed"]:
            assert engine.is_game_over() is True
            assert len(result["winners"]) > 0

    @pytest.mark.asyncio
    async def test_simulate_multiple_games(self):
        """Test that multiple simulations work."""
        completed_games = 0
        total_games = 5

        for i in range(total_games):
            engine = GameEngine(database_url="sqlite:///:memory:")

            await engine.init_database()

            config = GameConfig(5, [f"p{j}" for j in range(5)], seed=i)
            await engine.create_game(config)
            assert engine._current_state is not None

            result = await engine.simulate_to_completion(max_turns=200)

            if result["completed"]:
                completed_games += 1

        # Most games should complete
        assert completed_games >= total_games * 0.8  # At least 80% completion rate

    @pytest.mark.asyncio
    async def test_simulate_different_player_counts(self):
        """Test simulation with different player counts."""
        for player_count in [5, 7, 10]:
            engine = GameEngine(database_url="sqlite:///:memory:")
            await engine.init_database()
            player_ids = [f"p{i}" for i in range(player_count)]
            config = GameConfig(player_count, player_ids, seed=42)
            await engine.create_game(config)
            assert engine._current_state is not None

            result = await engine.simulate_to_completion(max_turns=150)

            # Should handle different player counts
            assert result["turns_taken"] > 0

    @pytest.mark.asyncio
    async def test_simulation_turn_limit(self):
        """Test simulation respects turn limits."""
        engine = GameEngine(database_url="sqlite:///:memory:")

        await engine.init_database()

        config = GameConfig(5, ["p1", "p2", "p3", "p4", "p5"], seed=42)
        await engine.create_game(config)
        assert engine._current_state is not None

        # Very low turn limit
        result = await engine.simulate_to_completion(max_turns=5)

        assert result["turns_taken"] <= 5
        # Game might not be completed with such low limit
        if not result["completed"]:
            assert not engine.is_game_over()


class TestConvenienceFunctions:
    """Test convenience functions."""

    @pytest.mark.asyncio
    async def test_create_game_function(self):
        """Test create_game convenience function."""
        player_ids = ["p1", "p2", "p3", "p4", "p5"]
        engine = await create_game(
            player_ids, seed=42, database_url="sqlite:///:memory:"
        )

        assert isinstance(engine, GameEngine)
        assert engine._current_state is not None
        assert len(engine._current_state.players) == 5

    @pytest.mark.asyncio
    async def test_run_random_game_function(self):
        """Test run_random_game convenience function."""
        result = await run_random_game(
            player_count=5, seed=42, database_url="sqlite:///:memory:"
        )

        assert "completed" in result
        assert "turns_taken" in result
        assert "winners" in result
        assert "final_stats" in result

        # Should have some reasonable results
        assert result["turns_taken"] > 0

    @pytest.mark.asyncio
    async def test_run_random_game_different_sizes(self):
        """Test run_random_game with different player counts."""
        for count in [5, 7, 10]:
            result = await run_random_game(
                player_count=count, seed=42, database_url="sqlite:///:memory:"
            )

            assert result["final_stats"]["player_count"] == count
            assert result["turns_taken"] > 0


class TestGameEngineEdgeCases:
    """Test edge cases and error conditions."""

    @pytest.mark.asyncio
    async def test_invalid_config(self):
        """Test game creation with invalid config."""
        engine = GameEngine(database_url="sqlite:///:memory:")
        await engine.init_database()

        # Invalid player count
        with pytest.raises(ValueError):
            config = GameConfig(4, ["p1", "p2", "p3", "p4"])
            await engine.create_game(config)

        # Mismatched player IDs
        with pytest.raises(ValueError):
            config = GameConfig(5, ["p1", "p2", "p3"])
            await engine.create_game(config)

    @pytest.mark.asyncio
    async def test_action_on_nonexistent_player(self):
        """Test performing action for nonexistent player."""
        engine = GameEngine(database_url="sqlite:///:memory:")

        await engine.init_database()

        config = GameConfig(5, ["p1", "p2", "p3", "p4", "p5"])
        await engine.create_game(config)
        assert engine._current_state is not None

        result = await engine.perform_action("nonexistent", ActionType.OBSERVE)
        assert result.success is False
        assert result.error is not None and "not found" in result.error

    @pytest.mark.asyncio
    async def test_multiple_game_creation(self):
        """Test creating multiple games with same engine."""
        engine = GameEngine(database_url="sqlite:///:memory:")
        await engine.init_database()

        # Create first game
        config1 = GameConfig(5, ["p1", "p2", "p3", "p4", "p5"])
        game_id_1 = await engine.create_game(config1)

        # Create second game (should replace first)
        config2 = GameConfig(6, ["a1", "a2", "a3", "a4", "a5", "a6"])
        game_id_2 = await engine.create_game(config2)
        assert engine._current_state is not None

        assert game_id_1 != game_id_2
        assert engine._current_state.game_id == game_id_2
        assert len(engine._current_state.players) == 6

    @pytest.mark.asyncio
    async def test_debug_get_full_state(self):
        """Test debug access to full state."""
        engine = GameEngine(database_url="sqlite:///:memory:")

        await engine.init_database()

        config = GameConfig(5, ["p1", "p2", "p3", "p4", "p5"])
        await engine.create_game(config)
        assert engine._current_state is not None

        debug_state = engine.debug_get_full_state()
        assert debug_state is not None

        # Should be a copy, not the same object
        assert debug_state is not engine._current_state
        assert debug_state.game_id == engine._current_state.game_id

    @pytest.mark.asyncio
    async def test_state_manager_integration(self):
        """Test integration with state manager."""
        engine = GameEngine(database_url="sqlite:///:memory:")

        await engine.init_database()

        config = GameConfig(5, ["p1", "p2", "p3", "p4", "p5"])
        await engine.create_game(config)
        assert engine._current_state is not None

        # Initial state should be saved
        current_state = engine.state_manager.get_current_state()
        assert current_state is not None
        assert current_state.game_id == engine._current_state.game_id

        # After action, new state should be saved
        director_id = engine._current_state.current_director.id
        eligible = [
            p.id
            for p in engine._current_state.players
            if p.id != director_id and not p.was_last_engineer
        ]

        await engine.perform_action(
            director_id, ActionType.NOMINATE, target_id=eligible[0]
        )

        updated_state = engine.state_manager.get_current_state()
        assert updated_state is not None
        assert updated_state.turn_number > current_state.turn_number
