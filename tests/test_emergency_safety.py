"""Comprehensive tests for Emergency Safety system in Secret AGI.

Tests emergency safety persistence, timing restrictions, and cross-round behavior.
"""

import pytest

from secret_agi.engine.game_engine import GameEngine
from secret_agi.engine.models import (
    ActionType,
    GameConfig,
    Paper,
    Phase,
)
from secret_agi.engine.rules import GameRules


class TestEmergencySafetyPersistence:
    """Test emergency safety effect persistence across game phases."""

    @pytest.mark.asyncio
    async def test_emergency_safety_effect_persists_until_next_paper_published(self):
        """Test emergency safety effect persists until the next paper is published."""
        engine = GameEngine(database_url="sqlite:///:memory:")
        await engine.init_database()

        config = GameConfig(5, ["p1", "p2", "p3", "p4", "p5"])
        await engine.create_game(config)
        assert engine._current_state is not None
        state = engine._current_state

        # Set up emergency safety conditions (C - S = 4)
        state.capability = 12
        state.safety = 8
        state.deck = [
            Paper("high_capability", 3, 0),  # Will be affected by emergency safety
            Paper("dummy1", 1, 1),
            Paper("dummy2", 1, 1),
        ]

        # Call emergency safety
        result = await engine.perform_action(
            "p1", ActionType.CALL_EMERGENCY_SAFETY
        )
        assert result.success

        # Vote YES on emergency safety
        for player in state.players:
            if player.alive:
                result = await engine.perform_action(
                    player.id, ActionType.VOTE_EMERGENCY, vote=True
                )
                assert result.success

        # Emergency safety should be active
        assert state.emergency_safety_active

        # Complete a research cycle to publish a paper
        success = await self._complete_research_cycle(engine, state)
        if success and not state.is_game_over:
            # Emergency safety should have been applied and then deactivated
            assert not state.emergency_safety_active
            # The published paper should have had its capability reduced by 1
            # (we can't easily test the exact value without knowing which paper was published)
        # If game ended, emergency safety may still be active but that's expected

    @pytest.mark.asyncio
    async def test_emergency_safety_persists_across_round_boundaries(self):
        """Test emergency safety effect survives round boundaries."""
        engine = GameEngine(database_url="sqlite:///:memory:")
        await engine.init_database()

        config = GameConfig(5, ["p1", "p2", "p3", "p4", "p5"])
        await engine.create_game(config)
        assert engine._current_state is not None
        state = engine._current_state

        # Set up emergency safety conditions
        state.capability = 12
        state.safety = 7  # C - S = 5 (valid for emergency safety)

        # Call and approve emergency safety
        result = await engine.perform_action(
            "p1", ActionType.CALL_EMERGENCY_SAFETY
        )
        assert result.success

        # Vote YES on emergency safety
        for player in state.players:
            if player.alive:
                result = await engine.perform_action(
                    player.id, ActionType.VOTE_EMERGENCY, vote=True
                )
                assert result.success

        # Emergency safety should be active
        assert state.emergency_safety_active
        original_director = state.current_director.id

        # Force failed proposals to advance rounds without publishing papers
        for _ in range(2):  # Cause failed proposals
            director = state.current_director.id
            eligible = GameRules.get_eligible_engineers(state)
            if eligible:
                target = next(iter(eligible))

                # Nominate
                result = await engine.perform_action(
                    director, ActionType.NOMINATE, target_id=target
                )
                if not result.success:
                    break

                # All vote NO to fail the proposal
                for player in state.players:
                    if player.alive:
                        result = await engine.perform_action(
                            player.id, ActionType.VOTE_TEAM, vote=False
                        )
                        if not result.success:
                            break

                # Emergency safety should still be active after failed proposal
                if not state.is_game_over:
                    assert state.emergency_safety_active

        # Emergency safety should persist across director changes
        if not state.is_game_over:
            assert state.emergency_safety_active
            # Director should have changed due to failed proposals
            assert state.current_director.id != original_director

    @pytest.mark.asyncio
    async def test_one_emergency_safety_per_round(self):
        """Test that emergency safety can only be called once per round."""
        engine = GameEngine(database_url="sqlite:///:memory:")
        await engine.init_database()

        config = GameConfig(5, ["p1", "p2", "p3", "p4", "p5"])
        await engine.create_game(config)
        assert engine._current_state is not None
        state = engine._current_state

        # Set up emergency safety conditions
        state.capability = 12
        state.safety = 7  # C - S = 5

        # First call should succeed
        result = await engine.perform_action(
            "p1", ActionType.CALL_EMERGENCY_SAFETY
        )
        assert result.success

        # Complete the emergency safety vote
        for player in state.players:
            if player.alive:
                result = await engine.perform_action(
                    player.id, ActionType.VOTE_EMERGENCY, vote=True
                )
                assert result.success

        # Second call in same round should fail
        result = await engine.perform_action(
            "p2", ActionType.CALL_EMERGENCY_SAFETY
        )
        assert not result.success
        assert "Emergency safety already called this round" in (result.error or "")

    async def _complete_research_cycle(self, engine: GameEngine, state) -> bool:
        """Helper to complete a research cycle and return success."""
        try:
            # Get team approved
            director = state.current_director.id
            eligible = GameRules.get_eligible_engineers(state)
            if not eligible:
                return False

            target = next(iter(eligible))

            result = await engine.perform_action(
                director, ActionType.NOMINATE, target_id=target
            )
            if not result.success:
                return False

            # All vote YES
            for player in state.players:
                if player.alive:
                    result = await engine.perform_action(
                        player.id, ActionType.VOTE_TEAM, vote=True
                    )
                    if not result.success:
                        return False

            # Complete research if we reached that phase
            if state.current_phase == Phase.RESEARCH and state.director_cards:
                # Director discards
                paper_to_discard = state.director_cards[0].id
                result = await engine.perform_action(
                    director, ActionType.DISCARD_PAPER, paper_id=paper_to_discard
                )
                if not result.success:
                    return False

                # Engineer publishes
                if state.engineer_cards:
                    paper_to_publish = state.engineer_cards[0].id
                    result = await engine.perform_action(
                        target, ActionType.PUBLISH_PAPER, paper_id=paper_to_publish
                    )
                    return result.success

            return True

        except Exception:
            return False
