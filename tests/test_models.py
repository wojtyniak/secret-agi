"""Unit tests for the models module."""

import pytest
from secret_agi.engine.models import (
    Paper, Player, GameState, GameConfig, GameUpdate, GameEvent,
    Role, Allegiance, Phase, ActionType, EventType,
    create_standard_deck, get_role_distribution
)


class TestPaper:
    """Test Paper model."""
    
    def test_paper_creation(self):
        """Test basic paper creation."""
        paper = Paper("test_paper", 2, 1)
        assert paper.id == "test_paper"
        assert paper.capability == 2
        assert paper.safety == 1
    
    def test_paper_validation(self):
        """Test paper validation."""
        # Valid papers
        Paper("valid1", 0, 0)
        Paper("valid2", 3, 2)
        
        # Invalid papers
        with pytest.raises(ValueError):
            Paper("invalid1", -1, 0)
        
        with pytest.raises(ValueError):
            Paper("invalid2", 0, -1)


class TestPlayer:
    """Test Player model."""
    
    def test_player_creation(self):
        """Test basic player creation."""
        player = Player("player1", Role.SAFETY, Allegiance.SAFETY)
        assert player.id == "player1"
        assert player.role == Role.SAFETY
        assert player.allegiance == Allegiance.SAFETY
        assert player.alive is True
        assert player.was_last_engineer is False
    
    def test_player_allegiance_auto_set(self):
        """Test that allegiance is set based on role."""
        safety_player = Player("p1", Role.SAFETY, Allegiance.SAFETY)
        assert safety_player.allegiance == Allegiance.SAFETY
        
        accel_player = Player("p2", Role.ACCELERATIONIST, Allegiance.ACCELERATION)
        assert accel_player.allegiance == Allegiance.ACCELERATION
        
        agi_player = Player("p3", Role.AGI, Allegiance.ACCELERATION)
        assert agi_player.allegiance == Allegiance.ACCELERATION


class TestGameEvent:
    """Test GameEvent model."""
    
    def test_event_creation(self):
        """Test event creation."""
        event = GameEvent.create(
            EventType.ACTION_ATTEMPTED,
            "player1",
            {"action": "nominate"},
            5
        )
        
        assert event.type == EventType.ACTION_ATTEMPTED
        assert event.player_id == "player1"
        assert event.data == {"action": "nominate"}
        assert event.turn_number == 5
        assert event.id is not None


class TestGameState:
    """Test GameState model."""
    
    def test_game_state_creation(self):
        """Test basic game state creation."""
        state = GameState("test_game")
        assert state.game_id == "test_game"
        assert state.turn_number == 0
        assert state.round_number == 1
        assert state.capability == 0
        assert state.safety == 0
        assert state.current_phase == Phase.TEAM_PROPOSAL
        assert state.is_game_over is False
    
    def test_current_director(self):
        """Test current director property."""
        players = [
            Player("p1", Role.SAFETY, Allegiance.SAFETY),
            Player("p2", Role.ACCELERATIONIST, Allegiance.ACCELERATION),
        ]
        
        state = GameState("test_game", players=players)
        state.current_director_index = 1
        
        assert state.current_director.id == "p2"
    
    def test_alive_players(self):
        """Test alive players property."""
        players = [
            Player("p1", Role.SAFETY, Allegiance.SAFETY, alive=True),
            Player("p2", Role.ACCELERATIONIST, Allegiance.ACCELERATION, alive=False),
            Player("p3", Role.AGI, Allegiance.ACCELERATION, alive=True),
        ]
        
        state = GameState("test_game", players=players)
        alive = state.alive_players
        
        assert len(alive) == 2
        assert alive[0].id == "p1"
        assert alive[1].id == "p3"
        assert state.alive_player_count == 2
    
    def test_get_player_by_id(self):
        """Test getting player by ID."""
        players = [
            Player("p1", Role.SAFETY, Allegiance.SAFETY),
            Player("p2", Role.ACCELERATIONIST, Allegiance.ACCELERATION),
        ]
        
        state = GameState("test_game", players=players)
        
        player = state.get_player_by_id("p2")
        assert player is not None
        assert player.id == "p2"
        
        player = state.get_player_by_id("nonexistent")
        assert player is None
    
    def test_get_next_director_index(self):
        """Test director rotation."""
        players = [
            Player("p1", Role.SAFETY, Allegiance.SAFETY, alive=True),
            Player("p2", Role.ACCELERATIONIST, Allegiance.ACCELERATION, alive=False),
            Player("p3", Role.AGI, Allegiance.ACCELERATION, alive=True),
        ]
        
        state = GameState("test_game", players=players)
        state.current_director_index = 0  # p1
        
        next_index = state.get_next_director_index()
        assert next_index == 2  # Should skip dead p2 and go to p3
        
        state.current_director_index = 2  # p3
        next_index = state.get_next_director_index()
        assert next_index == 0  # Should wrap around to p1
    
    def test_add_event(self):
        """Test adding events to game state."""
        state = GameState("test_game")
        state.turn_number = 5
        
        state.add_event(EventType.ACTION_ATTEMPTED, "player1", {"action": "vote"})
        
        assert len(state.events) == 1
        event = state.events[0]
        assert event.type == EventType.ACTION_ATTEMPTED
        assert event.player_id == "player1"
        assert event.turn_number == 5


class TestGameConfig:
    """Test GameConfig model."""
    
    def test_valid_config(self):
        """Test valid game configuration."""
        config = GameConfig(5, ["p1", "p2", "p3", "p4", "p5"])
        assert config.player_count == 5
        assert len(config.player_ids) == 5
    
    def test_invalid_player_count(self):
        """Test invalid player count validation."""
        with pytest.raises(ValueError):
            GameConfig(4, ["p1", "p2", "p3", "p4"])  # Too few
        
        with pytest.raises(ValueError):
            GameConfig(11, ["p1"] * 11)  # Too many
    
    def test_mismatched_player_ids(self):
        """Test mismatched player IDs validation."""
        with pytest.raises(ValueError):
            GameConfig(5, ["p1", "p2", "p3"])  # Too few IDs


class TestUtilityFunctions:
    """Test utility functions."""
    
    def test_create_standard_deck(self):
        """Test standard deck creation."""
        deck = create_standard_deck()
        
        assert len(deck) == 17
        
        # Check total capability and safety values
        total_capability = sum(p.capability for p in deck)
        total_safety = sum(p.safety for p in deck)
        
        assert total_capability == 26
        assert total_safety == 26
        
        # Check specific counts
        capability_counts = {}
        safety_counts = {}
        
        for paper in deck:
            cap_key = paper.capability
            safety_key = paper.safety
            
            capability_counts[cap_key] = capability_counts.get(cap_key, 0) + 1
            safety_counts[safety_key] = safety_counts.get(safety_key, 0) + 1
        
        # Verify distribution matches rules
        assert capability_counts[0] == 3  # 3x [C:0, S:2]
        assert capability_counts[1] == 6  # 2+2+2 cards with C:1
        assert capability_counts[2] == 4  # 2+2 cards with C:2
        assert capability_counts[3] == 4  # 2+2 cards with C:3
    
    def test_get_role_distribution(self):
        """Test role distribution for different player counts."""
        # Test all valid player counts
        for count in range(5, 11):
            distribution = get_role_distribution(count)
            
            # Check that total equals player count
            total = sum(distribution.values())
            assert total == count
            
            # Check that there's always exactly 1 AGI
            assert distribution[Role.AGI] == 1
            
            # Check that Safety is always the majority initially
            assert distribution[Role.SAFETY] >= distribution[Role.ACCELERATIONIST] + distribution[Role.AGI]
        
        # Test specific distributions
        assert get_role_distribution(5) == {Role.SAFETY: 3, Role.ACCELERATIONIST: 1, Role.AGI: 1}
        assert get_role_distribution(10) == {Role.SAFETY: 6, Role.ACCELERATIONIST: 3, Role.AGI: 1}
    
    def test_invalid_player_count_distribution(self):
        """Test invalid player count for role distribution."""
        with pytest.raises(ValueError):
            get_role_distribution(4)
        
        with pytest.raises(ValueError):
            get_role_distribution(11)


class TestGameUpdate:
    """Test GameUpdate model."""
    
    def test_game_update_creation(self):
        """Test game update creation."""
        update = GameUpdate(success=True, error=None)
        assert update.success is True
        assert update.error is None
        assert update.events == []
        assert update.valid_actions == []
        assert update.chat_messages == []
    
    def test_game_update_with_error(self):
        """Test game update with error."""
        update = GameUpdate(success=False, error="Invalid action")
        assert update.success is False
        assert update.error == "Invalid action"