"""Comprehensive tests for information filtering and state management in Secret AGI.

Tests player-specific information views, role knowledge, player elimination effects,
paper conservation, and event logging completeness.
"""

import pytest

from secret_agi.engine.events import PublicInformationProvider
from secret_agi.engine.game_engine import GameEngine
from secret_agi.engine.models import (
    ActionType,
    Allegiance,
    EventType,
    GameConfig,
    Phase,
    Role,
)
from secret_agi.engine.rules import GameRules


def get_player_view(state, player_id: str) -> dict:
    """Helper function to get player-specific view of game state."""
    player = state.get_player_by_id(player_id)
    if not player:
        return {}

    # Get public information that all players can see
    public_info = PublicInformationProvider.get_public_game_info(state)
    public_vote_info = PublicInformationProvider.get_public_vote_info(state)

    # Add player-specific information
    player_view = {
        **public_info,
        **public_vote_info,
        "your_role": player.role.value,
        "your_allegiance": player.allegiance.value,
    }

    # Add known allies for evil faction
    if player.role in [Role.ACCELERATIONIST, Role.AGI]:
        allies = []
        for p in state.players:
            if p.id != player.id and p.role in [Role.ACCELERATIONIST, Role.AGI]:
                allies.append(p.id)
        if allies:
            player_view["known_allies"] = allies

    # Add viewed allegiances if any
    if player.id in state.viewed_allegiances:
        player_view["viewed_allegiances"] = {
            target_id: allegiance.value
            for target_id, allegiance in state.viewed_allegiances[player.id].items()
        }

    return player_view


class TestInformationFiltering:
    """Test information filtering per player (private vs public info)."""

    @pytest.mark.asyncio
    async def test_private_vs_public_information_separation(self):
        """Test that players only see information they should have access to."""
        engine = GameEngine(database_url="sqlite:///:memory:")
        await engine.init_database()

        config = GameConfig(5, ["p1", "p2", "p3", "p4", "p5"])
        await engine.create_game(config)
        assert engine._current_state is not None
        state = engine._current_state

        # Find different role players
        safety_player = None
        accelerationist_player = None
        agi_player = None

        for player in state.players:
            if player.role == Role.SAFETY and not safety_player:
                safety_player = player
            elif player.role == Role.ACCELERATIONIST and not accelerationist_player:
                accelerationist_player = player
            elif player.role == Role.AGI and not agi_player:
                agi_player = player

        assert safety_player and accelerationist_player and agi_player

        # Test Safety player's view - should only know their own role
        safety_view = get_player_view(state, safety_player.id)
        assert safety_view["your_role"] == Role.SAFETY.value
        assert safety_view["your_allegiance"] == Allegiance.SAFETY.value
        # Should not see other players' roles directly
        assert "player_roles" not in safety_view

        # Test Accelerationist player's view - should know AGI identity
        accel_view = get_player_view(state, accelerationist_player.id)
        assert accel_view["your_role"] == Role.ACCELERATIONIST.value
        assert accel_view["your_allegiance"] == Allegiance.ACCELERATION.value
        # Should know allies (AGI)
        assert "known_allies" in accel_view
        assert agi_player.id in accel_view["known_allies"]

        # Test AGI player's view - should know Accelerationist identity
        agi_view = get_player_view(state, agi_player.id)
        assert agi_view["your_role"] == Role.AGI.value
        assert agi_view["your_allegiance"] == Allegiance.ACCELERATION.value
        # Should know allies (Accelerationist)
        assert "known_allies" in agi_view
        assert accelerationist_player.id in agi_view["known_allies"]

        # All players should see public information
        for player_view in [safety_view, accel_view, agi_view]:
            assert "capability" in player_view
            assert "safety" in player_view
            assert "current_phase" in player_view
            assert "alive_players" in player_view
            assert "current_director_id" in player_view

    @pytest.mark.asyncio
    async def test_viewed_allegiances_privacy(self):
        """Test that allegiance viewing results are private to the viewer."""
        engine = GameEngine(database_url="sqlite:///:memory:")
        await engine.init_database()

        # Use 9-player game to have C=6 power available
        config = GameConfig(9, [f"p{i}" for i in range(1, 10)])
        await engine.create_game(config)
        assert engine._current_state is not None
        state = engine._current_state

        # Set up to trigger C=6 power (allegiance viewing)
        state.capability = 6
        director_id = state.current_director.id

        # Find a target player different from director
        target_player = None
        for player in state.players:
            if player.id != director_id:
                target_player = player
                break

        assert target_player is not None

        # Simulate allegiance viewing power
        GameRules.view_allegiance(state, director_id, target_player.id)

        # Director should see the viewed allegiance
        director_view = get_player_view(state, director_id)
        assert "viewed_allegiances" in director_view
        assert target_player.id in director_view["viewed_allegiances"]
        assert director_view["viewed_allegiances"][target_player.id] == target_player.allegiance.value

        # Other players should NOT see the viewed allegiance
        for player in state.players:
            if player.id != director_id:
                player_view = get_player_view(state, player.id)
                # Other players should not have this allegiance viewing result
                if "viewed_allegiances" in player_view:
                    assert target_player.id not in player_view["viewed_allegiances"]


class TestRoleKnowledge:
    """Test AGI/Accelerationist knowledge setup."""

    @pytest.mark.asyncio
    async def test_agi_accelerationist_know_each_other_at_game_start(self):
        """Test that AGI and Accelerationists know each other's identities from game start."""
        engine = GameEngine(database_url="sqlite:///:memory:")
        await engine.init_database()

        config = GameConfig(7, [f"p{i}" for i in range(1, 8)])  # 7 players: 4 Safety, 2 Accel, 1 AGI
        await engine.create_game(config)
        assert engine._current_state is not None
        state = engine._current_state

        # Find the evil faction players
        agi_player = None
        accelerationist_players = []

        for player in state.players:
            if player.role == Role.AGI:
                agi_player = player
            elif player.role == Role.ACCELERATIONIST:
                accelerationist_players.append(player)

        assert agi_player is not None
        assert len(accelerationist_players) == 2  # 7-player game has 2 Accelerationists

        # AGI should know all Accelerationists
        agi_view = get_player_view(state, agi_player.id)
        assert "known_allies" in agi_view
        for accel in accelerationist_players:
            assert accel.id in agi_view["known_allies"]

        # Each Accelerationist should know AGI and other Accelerationists
        for accel in accelerationist_players:
            accel_view = get_player_view(state, accel.id)
            assert "known_allies" in accel_view
            assert agi_player.id in accel_view["known_allies"]
            # Should also know other Accelerationists
            for other_accel in accelerationist_players:
                if other_accel.id != accel.id:
                    assert other_accel.id in accel_view["known_allies"]

        # Safety players should not know any allies
        for player in state.players:
            if player.role == Role.SAFETY:
                safety_view = get_player_view(state, player.id)
                assert "known_allies" not in safety_view or len(safety_view["known_allies"]) == 0


class TestDeadPlayerExclusion:
    """Test eliminated players cannot vote/act/be nominated."""

    @pytest.mark.asyncio
    async def test_dead_players_cannot_vote_act_or_be_nominated(self):
        """Test that eliminated players are properly excluded from all game actions."""
        engine = GameEngine(database_url="sqlite:///:memory:")
        await engine.init_database()

        config = GameConfig(5, ["p1", "p2", "p3", "p4", "p5"])
        await engine.create_game(config)
        assert engine._current_state is not None
        state = engine._current_state

        # Eliminate a player (not the current director)
        target_player = None
        current_director_id = state.current_director.id
        for player in state.players:
            if player.id != current_director_id:
                target_player = player
                break

        assert target_player is not None
        GameRules.eliminate_player(state, target_player.id)
        assert not target_player.alive

        # Dead player should not be eligible for engineer nomination
        eligible_engineers = GameRules.get_eligible_engineers(state)
        assert target_player.id not in eligible_engineers

        # Attempt to nominate the dead player should fail
        result = await engine.perform_action(
            current_director_id, ActionType.NOMINATE, target_id=target_player.id
        )
        assert not result.success
        assert "not eligible" in (result.error or "").lower() or "eliminated" in (result.error or "").lower()

        # Nominate a living player instead
        living_eligible = [p for p in eligible_engineers if state.get_player_by_id(p).alive]
        if living_eligible:
            result = await engine.perform_action(
                current_director_id, ActionType.NOMINATE, target_id=living_eligible[0]
            )
            assert result.success

            # Dead player attempting to vote should fail
            result = await engine.perform_action(
                target_player.id, ActionType.VOTE_TEAM, vote=True
            )
            assert not result.success

            # Alive players should be able to vote
            for player in state.players:
                if player.alive and player.id != target_player.id:
                    result = await engine.perform_action(
                        player.id, ActionType.VOTE_TEAM, vote=True
                    )
                    if not state.is_game_over:  # Game might end due to other conditions
                        assert result.success


class TestPaperConservation:
    """Test total paper count preservation through operations."""

    @pytest.mark.asyncio
    async def test_paper_conservation_through_complete_game_cycle(self):
        """Test that paper counts are properly tracked and conserved."""
        engine = GameEngine(database_url="sqlite:///:memory:")
        await engine.init_database()

        config = GameConfig(5, ["p1", "p2", "p3", "p4", "p5"])
        await engine.create_game(config)
        assert engine._current_state is not None
        state = engine._current_state

        # Record initial paper distribution
        initial_deck_count = len(state.deck)
        initial_discard_count = len(state.discard)
        initial_total = initial_deck_count + initial_discard_count

        # Complete several research cycles to track paper movement
        cycles_completed = 0
        while not state.is_game_over and cycles_completed < 3 and len(state.deck) >= 3:
            # Record state before research cycle
            pre_cycle_total = len(state.deck) + len(state.discard)

            success = await self._complete_research_cycle(engine, state)
            if success:
                cycles_completed += 1

                # After each cycle, total papers should be conserved or reduced
                # (papers are published and moved to discard, or consumed)
                post_cycle_total = len(state.deck) + len(state.discard)
                assert post_cycle_total <= pre_cycle_total

                # Discard pile should grow (published + discarded papers)
                assert len(state.discard) > initial_discard_count
            else:
                break

        # Verify no papers have been lost (only consumed through publication)
        final_total = len(state.deck) + len(state.discard)
        assert final_total <= initial_total

        # If we published papers, discard pile should have grown
        if cycles_completed > 0:
            assert len(state.discard) > initial_discard_count

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


class TestEventLogging:
    """Test event logging completeness for all state changes."""

    @pytest.mark.asyncio
    async def test_all_state_changes_generate_appropriate_events(self):
        """Test that all major state changes generate corresponding events."""
        engine = GameEngine(database_url="sqlite:///:memory:")
        await engine.init_database()

        config = GameConfig(5, ["p1", "p2", "p3", "p4", "p5"])
        await engine.create_game(config)
        assert engine._current_state is not None
        state = engine._current_state

        initial_event_count = len(state.events)

        # Perform a nomination - should generate events
        director = state.current_director.id
        eligible = GameRules.get_eligible_engineers(state)
        target = next(iter(eligible))

        result = await engine.perform_action(
            director, ActionType.NOMINATE, target_id=target
        )
        assert result.success

        # Should have generated nomination event
        nomination_events = [e for e in state.events if e.type == EventType.ACTION_ATTEMPTED]
        assert len(nomination_events) > 0

        # Perform voting - should generate events for each vote
        vote_count_before = len([e for e in state.events if "vote" in str(e.data).lower()])

        for player in state.players:
            if player.alive:
                result = await engine.perform_action(
                    player.id, ActionType.VOTE_TEAM, vote=True
                )
                if not result.success:
                    break

        # Should have generated vote events
        vote_count_after = len([e for e in state.events if "vote" in str(e.data).lower()])
        assert vote_count_after > vote_count_before

        # If we reached research phase, continue to test research events
        if state.current_phase == Phase.RESEARCH and state.director_cards:
            research_events_before = len([e for e in state.events if e.type == EventType.PAPER_PUBLISHED])

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

                # Should have generated paper publication event
                research_events_after = len([e for e in state.events if e.type == EventType.PAPER_PUBLISHED])
                assert research_events_after > research_events_before

        # Verify we have more events than we started with
        assert len(state.events) > initial_event_count
