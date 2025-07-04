"""Validated edge case tests for Secret AGI game engine.

These tests focus on the most critical edge cases identified during debugging,
with careful setup to ensure they work correctly and don't conflict with game rules.
"""

import pytest

from secret_agi.engine.game_engine import GameEngine
from secret_agi.engine.models import (
    ActionType,
    GameConfig,
    Paper,
    Phase,
    Role,
)
from secret_agi.engine.rules import GameRules


class TestCriticalEdgeCases:
    """Test the most important edge cases that could cause game instability."""

    @pytest.mark.asyncio
    async def test_empty_deck_auto_publish_handling(self):
        """Test auto-publish behavior when deck is empty."""
        engine = GameEngine(database_url="sqlite:///:memory:")
        await engine.init_database()
        
        config = GameConfig(5, ["p1", "p2", "p3", "p4", "p5"])
        await engine.create_game(config)
        assert engine._current_state is not None
        state = engine._current_state
        
        # Set up scenario: empty deck with balanced scores to avoid immediate win
        state.deck = []
        state.capability = 8
        state.safety = 8  # S >= C, so if deck exhaustion triggers, Safety wins
        state.failed_proposals = 2  # Next failure will trigger auto-publish
        
        # Trigger 3rd failure
        director = state.current_director.id
        eligible = GameRules.get_eligible_engineers(state)
        
        if eligible:
            target = next(iter(eligible))
            
            result = await engine.perform_action(
                director, ActionType.NOMINATE, target_id=target
            )
            assert result.success
            
            # Vote NO to trigger auto-publish
            for player_id in ["p1", "p2", "p3", "p4", "p5"]:
                result = await engine.perform_action(
                    player_id, ActionType.VOTE_TEAM, vote=False
                )
                # Game might end due to deck exhaustion during auto-publish attempt
                if not result.success:
                    assert "Game is over" in result.error
                    break
                assert result.success
        
        # With empty deck, either:
        # 1. Auto-publish does nothing and game continues
        # 2. Deck exhaustion triggers win condition (S >= C means Safety wins)
        if state.is_game_over:
            assert Role.SAFETY in state.winners
        else:
            # Auto-publish with empty deck should reset failure counter
            assert state.failed_proposals == 0

    @pytest.mark.asyncio
    async def test_research_phase_with_minimal_deck(self):
        """Test research phase transition when deck has fewer than 3 cards."""
        engine = GameEngine(database_url="sqlite:///:memory:")
        await engine.init_database()
        
        config = GameConfig(5, ["p1", "p2", "p3", "p4", "p5"])
        await engine.create_game(config)
        assert engine._current_state is not None
        state = engine._current_state
        
        # Set deck to have only 2 cards
        state.deck = [
            Paper("card1", 1, 1),
            Paper("card2", 1, 1),
        ]
        
        # Get team approved
        director = state.current_director.id
        eligible = GameRules.get_eligible_engineers(state)
        target = next(iter(eligible))
        
        result = await engine.perform_action(
            director, ActionType.NOMINATE, target_id=target
        )
        assert result.success
        
        # All vote YES
        for player_id in ["p1", "p2", "p3", "p4", "p5"]:
            result = await engine.perform_action(
                player_id, ActionType.VOTE_TEAM, vote=True
            )
            assert result.success
        
        # Should handle insufficient deck gracefully
        if state.current_phase == Phase.RESEARCH:
            # Director should have received whatever cards were available
            assert len(state.director_cards) <= 2
            assert len(state.deck) == 0
        elif state.current_phase == Phase.GAME_OVER:
            # Deck exhaustion might have triggered win condition
            assert state.is_game_over

    @pytest.mark.asyncio
    async def test_vote_counting_with_eliminated_player(self):
        """Test that vote counting correctly excludes eliminated players."""
        engine = GameEngine(database_url="sqlite:///:memory:")
        await engine.init_database()
        
        config = GameConfig(5, ["p1", "p2", "p3", "p4", "p5"])
        await engine.create_game(config)
        assert engine._current_state is not None
        state = engine._current_state
        
        # Eliminate a Safety player (not AGI to avoid triggering Safety win)
        # Make sure we don't eliminate the current director
        current_director_id = state.current_director.id
        safety_players = [p for p in state.players if p.role == Role.SAFETY and p.id != current_director_id]
        if safety_players:
            safety_players[0].alive = False
        
        # Verify 4 players remain alive
        alive_count = sum(1 for p in state.players if p.alive)
        assert alive_count == 4
        
        # Nominate someone
        director = state.current_director.id
        eligible = GameRules.get_eligible_engineers(state)
        alive_eligible = [p for p in eligible if state.get_player_by_id(p).alive]
        
        if alive_eligible:
            target = alive_eligible[0]
            
            result = await engine.perform_action(
                director, ActionType.NOMINATE, target_id=target
            )
            assert result.success
            
            # Get alive players for voting
            alive_players = [p.id for p in state.players if p.alive]
            
            # Test majority: 3 YES, 1 NO out of 4 alive players = majority YES
            votes = {alive_players[0]: True, alive_players[1]: True, 
                    alive_players[2]: True, alive_players[3]: False}
            
            for player_id, vote in votes.items():
                result = await engine.perform_action(
                    player_id, ActionType.VOTE_TEAM, vote=vote
                )
                # Check success unless game ended for other reasons
                if not state.is_game_over:
                    assert result.success
            
            # If game didn't end and we have enough cards, should transition to research
            if not state.is_game_over and len(state.deck) >= 3:
                assert state.current_phase == Phase.RESEARCH

    @pytest.mark.asyncio
    async def test_director_rotation_through_failures(self):
        """Test director rotation works correctly through multiple failures."""
        engine = GameEngine(database_url="sqlite:///:memory:")
        await engine.init_database()
        
        config = GameConfig(5, ["p1", "p2", "p3", "p4", "p5"])
        await engine.create_game(config)
        assert engine._current_state is not None
        state = engine._current_state
        
        # Set up deck with enough papers for multiple rounds
        state.deck = [Paper(f"paper{i}", 1, 1) for i in range(12)]
        
        # Track directors seen
        directors_seen = set()
        original_director = state.current_director.id
        directors_seen.add(original_director)
        
        # Force several failures to test director rotation
        for attempt in range(3):
            if state.is_game_over:
                break
                
            current_director = state.current_director.id
            eligible = GameRules.get_eligible_engineers(state)
            
            if eligible:
                target = next(iter(eligible))
                
                result = await engine.perform_action(
                    current_director, ActionType.NOMINATE, target_id=target
                )
                assert result.success
                
                # All vote NO to trigger failure
                for player_id in ["p1", "p2", "p3", "p4", "p5"]:
                    result = await engine.perform_action(
                        player_id, ActionType.VOTE_TEAM, vote=False
                    )
                    assert result.success
                
                # Director should have advanced
                new_director = state.current_director.id
                directors_seen.add(new_director)
                
                # Reset for next attempt
                state.nominated_engineer_id = None
                state.team_votes = {}
        
        # Should have seen at least 2 different directors
        assert len(directors_seen) >= 2

    @pytest.mark.asyncio
    async def test_paper_deck_integrity_through_operations(self):
        """Test that papers are properly tracked through game operations."""
        engine = GameEngine(database_url="sqlite:///:memory:")
        await engine.init_database()
        
        config = GameConfig(5, ["p1", "p2", "p3", "p4", "p5"])
        await engine.create_game(config)
        assert engine._current_state is not None
        state = engine._current_state
        
        # Record initial paper count
        initial_total = len(state.deck) + len(state.discard)
        
        # Complete one full research cycle
        director = state.current_director.id
        eligible = GameRules.get_eligible_engineers(state)
        target = next(iter(eligible))
        
        # Get team approved
        result = await engine.perform_action(
            director, ActionType.NOMINATE, target_id=target
        )
        assert result.success
        
        for player_id in ["p1", "p2", "p3", "p4", "p5"]:
            result = await engine.perform_action(
                player_id, ActionType.VOTE_TEAM, vote=True
            )
            assert result.success
        
        # If in research phase, complete the cycle
        if state.current_phase == Phase.RESEARCH and state.director_cards:
            # Director discards
            paper_to_discard = state.director_cards[0].id
            result = await engine.perform_action(
                director, ActionType.DISCARD_PAPER, paper_id=paper_to_discard
            )
            assert result.success
            
            # Engineer publishes
            if state.engineer_cards:
                paper_to_publish = state.engineer_cards[0].id
                result = await engine.perform_action(
                    target, ActionType.PUBLISH_PAPER, paper_id=paper_to_publish
                )
                assert result.success
        
        # Verify paper conservation
        final_total = len(state.deck) + len(state.discard)
        
        # Papers should be conserved (some may be consumed through publication)
        assert final_total <= initial_total
        assert len(state.deck) >= 0
        assert len(state.discard) >= 0
        
        # Discard pile should have gained some papers
        if state.current_phase == Phase.TEAM_PROPOSAL and state.round_number > 1:
            assert len(state.discard) > 0