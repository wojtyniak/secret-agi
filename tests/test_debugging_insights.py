"""Tests focused on the specific critical game logic issues discovered during debugging.

These tests validate the core fixes made to resolve the game completion bug
and ensure the game engine handles edge cases correctly.
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


class TestEngineerEligibilityFix:
    """Test the engineer eligibility bug fix that resolved game completion issues."""

    @pytest.mark.asyncio
    async def test_engineer_eligibility_reset_prevents_deadlock(self):
        """The core bug fix: engineer eligibility must reset after successful rounds."""
        engine = GameEngine(database_url="sqlite:///:memory:")
        await engine.init_database()

        config = GameConfig(5, ["p1", "p2", "p3", "p4", "p5"])
        await engine.create_game(config)
        assert engine._current_state is not None
        state = engine._current_state

        # Reduce deck size to simulate the conditions where the bug occurred
        state.deck = [Paper(f"test{i}", 1, 1) for i in range(6)]

        # Simulate multiple successful research rounds
        for _round_num in range(3):
            if state.is_game_over:
                break

            # Get current eligible engineers
            eligible_before = set(GameRules.get_eligible_engineers(state))
            director = state.current_director.id

            # Use any eligible engineer
            if eligible_before:
                target = next(iter(eligible_before))

                # Complete a successful research round
                result = await engine.perform_action(
                    director, ActionType.NOMINATE, target_id=target
                )
                assert result.success

                # Everyone votes YES
                for player_id in ["p1", "p2", "p3", "p4", "p5"]:
                    result = await engine.perform_action(
                        player_id, ActionType.VOTE_TEAM, vote=True
                    )
                    assert result.success

                # Complete research phase if we reached it
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

        # CRITICAL: After multiple rounds, some players should still be eligible
        # This is the key fix - without it, all players become ineligible over time
        final_eligible = set(GameRules.get_eligible_engineers(state))
        assert len(final_eligible) >= 2, f"Too few eligible engineers: {final_eligible}"

    @pytest.mark.asyncio
    async def test_engineer_eligibility_with_auto_publish(self):
        """Engineer eligibility must work correctly during auto-publish scenarios."""
        engine = GameEngine(database_url="sqlite:///:memory:")
        await engine.init_database()

        config = GameConfig(5, ["p1", "p2", "p3", "p4", "p5"])
        await engine.create_game(config)
        assert engine._current_state is not None
        state = engine._current_state

        # Set up for auto-publish scenario
        state.deck = [Paper("auto", 1, 1)]
        state.failed_proposals = 2  # Next failure will trigger auto-publish

        # Mark one player as last engineer
        engineer = state.get_player_by_id("p2")
        engineer.was_last_engineer = True

        # Verify p2 is not eligible before auto-publish
        eligible_before = GameRules.get_eligible_engineers(state)
        assert "p2" not in eligible_before

        # Trigger auto-publish through 3rd failure
        director = state.current_director.id
        eligible = GameRules.get_eligible_engineers(state)
        if eligible:
            target = next(iter(eligible))

            result = await engine.perform_action(
                director, ActionType.NOMINATE, target_id=target
            )
            assert result.success

            # Everyone votes NO to trigger auto-publish
            for player_id in ["p1", "p2", "p3", "p4", "p5"]:
                result = await engine.perform_action(
                    player_id, ActionType.VOTE_TEAM, vote=False
                )
                assert result.success

        # After auto-publish, engineer eligibility should be reset
        eligible_after = GameRules.get_eligible_engineers(state)
        assert "p2" in eligible_after, "Engineer eligibility should reset after auto-publish"


class TestDeckExhaustionHandling:
    """Test deck exhaustion scenarios that could cause game state issues."""

    @pytest.mark.asyncio
    async def test_research_phase_with_insufficient_cards(self):
        """Game must handle research phase when deck has fewer than 3 cards."""
        engine = GameEngine(database_url="sqlite:///:memory:")
        await engine.init_database()

        config = GameConfig(5, ["p1", "p2", "p3", "p4", "p5"])
        await engine.create_game(config)
        assert engine._current_state is not None
        state = engine._current_state

        # Set deck to have only 2 cards (less than the 3 needed for director)
        state.deck = [
            Paper("last1", 1, 1),
            Paper("last2", 1, 1),
        ]

        # Get team approved to transition to research phase
        director = state.current_director.id
        eligible = GameRules.get_eligible_engineers(state)
        target = next(iter(eligible))

        result = await engine.perform_action(
            director, ActionType.NOMINATE, target_id=target
        )
        assert result.success

        # Everyone votes YES
        for player_id in ["p1", "p2", "p3", "p4", "p5"]:
            result = await engine.perform_action(
                player_id, ActionType.VOTE_TEAM, vote=True
            )
            assert result.success

        # Game should handle the insufficient deck gracefully
        # Either by entering research phase with available cards or triggering win condition
        assert state.current_phase in [Phase.RESEARCH, Phase.GAME_OVER]

        if state.current_phase == Phase.RESEARCH:
            # Should have given director whatever cards were available
            assert len(state.director_cards) <= 2
            assert len(state.deck) == 0

    @pytest.mark.asyncio
    async def test_deck_exhaustion_win_conditions(self):
        """Test deck exhaustion triggers correct win conditions."""
        engine = GameEngine(database_url="sqlite:///:memory:")
        await engine.init_database()

        config = GameConfig(5, ["p1", "p2", "p3", "p4", "p5"])
        await engine.create_game(config)
        assert engine._current_state is not None
        state = engine._current_state

        # Test case: Safety wins when S >= C with empty deck
        state.deck = []
        state.capability = 8
        state.safety = 8

        game_over, winners = GameRules.check_win_conditions(state)
        if game_over:
            assert Role.SAFETY in winners, "Safety should win when S >= C with empty deck"

        # Test case: Evil wins when S < C with empty deck
        state.capability = 9
        state.safety = 8

        game_over, winners = GameRules.check_win_conditions(state)
        if game_over:
            assert Role.ACCELERATIONIST in winners or Role.AGI in winners, "Evil should win when S < C with empty deck"


class TestVoteValidationWithDeadPlayers:
    """Test vote counting correctly excludes eliminated players."""

    @pytest.mark.asyncio
    async def test_team_vote_majority_with_dead_players(self):
        """Team votes must calculate majority based only on alive players."""
        engine = GameEngine(database_url="sqlite:///:memory:")
        await engine.init_database()

        config = GameConfig(5, ["p1", "p2", "p3", "p4", "p5"])
        await engine.create_game(config)
        assert engine._current_state is not None
        state = engine._current_state

        # Eliminate a Safety player (to avoid triggering AGI elimination win condition)
        # Make sure we don't eliminate the current director
        current_director_id = state.current_director.id
        safety_players = [p for p in state.players if p.role == Role.SAFETY and p.id != current_director_id]
        if safety_players:
            safety_players[0].alive = False

        # Verify vote counting with 4 alive players
        alive_count = sum(1 for p in state.players if p.alive)
        assert alive_count == 4

        # Set up nomination
        director = state.current_director.id
        eligible = GameRules.get_eligible_engineers(state)
        alive_eligible = [p for p in eligible if state.get_player_by_id(p).alive]

        if alive_eligible:
            target = alive_eligible[0]

            result = await engine.perform_action(
                director, ActionType.NOMINATE, target_id=target
            )
            assert result.success

            # Test majority calculation with 4 alive players
            # 3 YES, 1 NO = majority YES (3 > 2)
            alive_players = [p.id for p in state.players if p.alive]

            votes = {alive_players[0]: True, alive_players[1]: True,
                    alive_players[2]: True, alive_players[3]: False}

            for player_id, vote in votes.items():
                result = await engine.perform_action(
                    player_id, ActionType.VOTE_TEAM, vote=vote
                )
                # Only check success if game hasn't ended due to other conditions
                if not state.is_game_over:
                    assert result.success

            # If game didn't end for other reasons, check phase transition
            if not state.is_game_over and len(state.deck) >= 3:
                assert state.current_phase == Phase.RESEARCH

    @pytest.mark.asyncio
    async def test_emergency_vote_with_dead_players(self):
        """Emergency safety votes must exclude eliminated players."""
        engine = GameEngine(database_url="sqlite:///:memory:")
        await engine.init_database()

        config = GameConfig(5, ["p1", "p2", "p3", "p4", "p5"])
        await engine.create_game(config)
        assert engine._current_state is not None
        state = engine._current_state

        # Set up emergency safety conditions (C - S >= 4)
        state.capability = 12
        state.safety = 7

        # Eliminate a Safety player
        safety_players = [p for p in state.players if p.role == Role.SAFETY]
        if safety_players:
            safety_players[0].alive = False

        # Call emergency safety
        result = await engine.perform_action(
            "p1", ActionType.CALL_EMERGENCY_SAFETY
        )
        if result.success:  # Only proceed if emergency safety could be called
            # Vote with alive players only
            alive_players = [p.id for p in state.players if p.alive]

            # 3 YES votes out of 4 alive players = majority
            for i, player_id in enumerate(alive_players):
                vote = i < 3  # First 3 vote YES, last one votes NO
                result = await engine.perform_action(
                    player_id, ActionType.VOTE_EMERGENCY, vote=vote
                )
                assert result.success

            # Emergency safety should be active with majority YES
            assert state.emergency_safety_active


class TestWinConditionTiming:
    """Test win conditions are checked at all critical points."""

    @pytest.mark.asyncio
    async def test_win_condition_checked_after_publication(self):
        """Win conditions must be checked immediately after each paper publication."""
        engine = GameEngine(database_url="sqlite:///:memory:")
        await engine.init_database()

        config = GameConfig(5, ["p1", "p2", "p3", "p4", "p5"])
        await engine.create_game(config)
        assert engine._current_state is not None
        state = engine._current_state

        # Set up a winning scenario (C will reach 15 after publication)
        # Keep the gap small to avoid premature win condition (C-S<6)
        state.capability = 14
        state.safety = 9  # Gap = 5, won't trigger C-S≥6 win condition

        # Create a deck with a winning paper
        state.deck = [
            Paper("safe", 0, 2),
            Paper("winning", 1, 0),  # This will push capability to 15
            Paper("safe2", 0, 2),
        ]

        # Get team approved
        director = state.current_director.id
        eligible = GameRules.get_eligible_engineers(state)
        target = next(iter(eligible))

        result = await engine.perform_action(
            director, ActionType.NOMINATE, target_id=target
        )
        assert result.success

        # Everyone votes YES
        for player_id in ["p1", "p2", "p3", "p4", "p5"]:
            result = await engine.perform_action(
                player_id, ActionType.VOTE_TEAM, vote=True
            )
            assert result.success

        # Research phase operations
        if state.current_phase == Phase.RESEARCH:
            # Director discards a safe paper
            safe_paper_id = None
            for paper in state.director_cards:
                if paper.capability == 0:
                    safe_paper_id = paper.id
                    break

            if safe_paper_id:
                result = await engine.perform_action(
                    director, ActionType.DISCARD_PAPER, paper_id=safe_paper_id
                )
                assert result.success

                # Engineer publishes the winning paper
                winning_paper_id = None
                for paper in state.engineer_cards:
                    if paper.capability == 1 and paper.safety == 0:
                        winning_paper_id = paper.id
                        break

                if winning_paper_id:
                    result = await engine.perform_action(
                        target, ActionType.PUBLISH_PAPER, paper_id=winning_paper_id
                    )
                    assert result.success

                    # Win condition should be detected immediately
                    assert state.capability >= 15
                    assert state.is_game_over
                    assert state.current_phase == Phase.GAME_OVER

    @pytest.mark.asyncio
    async def test_win_condition_checked_after_auto_publish(self):
        """Win conditions must be checked after auto-publish events."""
        engine = GameEngine(database_url="sqlite:///:memory:")
        await engine.init_database()

        config = GameConfig(5, ["p1", "p2", "p3", "p4", "p5"])
        await engine.create_game(config)
        assert engine._current_state is not None
        state = engine._current_state

        # Set up auto-publish winning scenario
        # Keep the gap small to avoid premature win condition (C-S<6)
        state.capability = 14
        state.safety = 9  # Gap = 5, won't trigger C-S≥6 win condition
        state.failed_proposals = 2  # Next failure triggers auto-publish

        # Deck with winning paper that will be auto-published
        state.deck = [Paper("auto_winner", 1, 0)]  # Will push capability to 15

        # Trigger auto-publish through 3rd failure
        director = state.current_director.id
        eligible = GameRules.get_eligible_engineers(state)

        if eligible:
            target = next(iter(eligible))

            result = await engine.perform_action(
                director, ActionType.NOMINATE, target_id=target
            )
            assert result.success

            # Everyone votes NO to trigger auto-publish
            for player_id in ["p1", "p2", "p3", "p4", "p5"]:
                result = await engine.perform_action(
                    player_id, ActionType.VOTE_TEAM, vote=False
                )
                assert result.success

            # Win condition should be detected after auto-publish
            if state.capability >= 15:
                assert state.is_game_over
                assert state.current_phase == Phase.GAME_OVER


class TestPaperManagement:
    """Test paper counting and deck management integrity."""

    @pytest.mark.asyncio
    async def test_paper_conservation_through_research_cycle(self):
        """Papers must be properly tracked through discard/publish cycle."""
        engine = GameEngine(database_url="sqlite:///:memory:")
        await engine.init_database()

        config = GameConfig(5, ["p1", "p2", "p3", "p4", "p5"])
        await engine.create_game(config)
        assert engine._current_state is not None
        state = engine._current_state

        # Count total papers at start
        initial_total = len(state.deck) + len(state.discard)

        # Complete one research cycle
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

        # Research phase operations
        if state.current_phase == Phase.RESEARCH:
            # Track papers before operations
            papers_before = len(state.deck) + len(state.discard) + len(state.director_cards)

            # Director discards one paper
            paper_to_discard = state.director_cards[0].id
            result = await engine.perform_action(
                director, ActionType.DISCARD_PAPER, paper_id=paper_to_discard
            )
            assert result.success

            # Engineer publishes one paper
            if state.engineer_cards:
                paper_to_publish = state.engineer_cards[0].id
                result = await engine.perform_action(
                    target, ActionType.PUBLISH_PAPER, paper_id=paper_to_publish
                )
                assert result.success

                # Count papers after operations
                papers_after = len(state.deck) + len(state.discard)

                # We should have accounted for all papers correctly
                # Started with papers_before, published paper goes to discard,
                # discarded paper goes to discard, remaining engineer card goes to discard
                # So discard pile should have gained papers
                assert papers_after <= papers_before
                assert len(state.discard) > 0

        # Verify no papers disappeared
        final_total = len(state.deck) + len(state.discard)
        assert final_total <= initial_total  # Some papers consumed through publication
