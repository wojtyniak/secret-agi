"""Integration tests for the complete Secret AGI game system."""

import pytest

from secret_agi.engine.game_engine import GameEngine, run_random_game
from secret_agi.engine.models import ActionType, GameConfig, Phase, Role
from secret_agi.players.random_player import BiasedRandomPlayer, RandomPlayer


class TestCompleteGameFlow:
    """Test complete game flows from start to finish."""

    @pytest.mark.asyncio
    async def test_basic_game_flow(self):
        """Test a basic game flow through multiple phases."""
        engine = GameEngine(database_url="sqlite:///:memory:")

        await engine.init_database()

        config = GameConfig(5, ["p1", "p2", "p3", "p4", "p5"], seed=42)
        await engine.create_game(config)
        assert engine._current_state is not None

        # Initial state
        assert engine._current_state is not None
        assert engine._current_state.current_phase == Phase.TEAM_PROPOSAL
        assert engine._current_state.turn_number == 0

        director_id = engine._current_state.current_director.id
        eligible_engineers = [
            p.id
            for p in engine._current_state.players
            if p.id != director_id and not p.was_last_engineer
        ]

        # Step 1: Director nominates engineer
        result = await engine.perform_action(
            director_id, ActionType.NOMINATE, target_id=eligible_engineers[0]
        )
        assert result.success is True
        assert engine._current_state.nominated_engineer_id == eligible_engineers[0]

        # Step 2: All players vote on team (majority yes)
        for player in engine._current_state.players:
            result = await engine.perform_action(
                player.id, ActionType.VOTE_TEAM, vote=True
            )
            assert result.success is True

        # Should transition to research phase
        assert engine._current_state.current_phase == Phase.RESEARCH  # type: ignore[comparison-overlap]
        assert engine._current_state.director_cards is not None
        assert len(engine._current_state.director_cards) <= 3

        # Step 3: Director discards a paper
        paper_to_discard = engine._current_state.director_cards[0]
        result = await engine.perform_action(
            director_id, ActionType.DISCARD_PAPER, paper_id=paper_to_discard.id
        )
        assert result.success is True
        assert engine._current_state.director_cards is None
        assert engine._current_state.engineer_cards is not None
        assert len(engine._current_state.engineer_cards) == 2

        # Step 4: Engineer publishes a paper
        engineer_id = engine._current_state.nominated_engineer_id
        paper_to_publish = engine._current_state.engineer_cards[0]
        old_capability = engine._current_state.capability
        old_safety = engine._current_state.safety

        result = await engine.perform_action(
            engineer_id, ActionType.PUBLISH_PAPER, paper_id=paper_to_publish.id
        )
        assert result.success is True

        # Board should be updated
        assert engine._current_state.capability >= old_capability
        assert engine._current_state.safety >= old_safety

        # Should return to team proposal phase for next round
        assert engine._current_state.current_phase == Phase.TEAM_PROPOSAL
        assert engine._current_state.round_number == 2

    @pytest.mark.asyncio
    async def test_failed_proposal_flow(self):
        """Test the flow when team proposals fail."""
        engine = GameEngine(database_url="sqlite:///:memory:")

        await engine.init_database()

        config = GameConfig(5, ["p1", "p2", "p3", "p4", "p5"], seed=42)
        await engine.create_game(config)
        assert engine._current_state is not None

        director_id = engine._current_state.current_director.id
        eligible_engineers = [
            p.id
            for p in engine._current_state.players
            if p.id != director_id and not p.was_last_engineer
        ]

        # Nominate engineer
        await engine.perform_action(
            director_id, ActionType.NOMINATE, target_id=eligible_engineers[0]
        )

        # Vote fails (majority no)
        votes = [True, False, False, False, False]  # Only one yes vote
        for i, player in enumerate(engine._current_state.players):
            await engine.perform_action(player.id, ActionType.VOTE_TEAM, vote=votes[i])

        # Should stay in team proposal, increment failures, advance director
        assert engine._current_state.current_phase == Phase.TEAM_PROPOSAL
        assert engine._current_state.failed_proposals == 1
        assert engine._current_state.current_director.id != director_id
        assert engine._current_state.nominated_engineer_id is None

    @pytest.mark.asyncio
    async def test_emergency_safety_flow(self):
        """Test emergency safety mechanism."""
        engine = GameEngine(database_url="sqlite:///:memory:")

        await engine.init_database()

        config = GameConfig(5, ["p1", "p2", "p3", "p4", "p5"], seed=42)
        await engine.create_game(config)
        assert engine._current_state is not None

        # Set up conditions for emergency safety
        engine._current_state.capability = 6
        engine._current_state.safety = 1  # diff = 5, triggers emergency

        # Any player can call emergency safety
        caller_id = engine._current_state.players[0].id
        result = await engine.perform_action(
            caller_id, ActionType.CALL_EMERGENCY_SAFETY
        )
        assert result.success is True
        assert engine._current_state.emergency_safety_called is True

        # All players vote on emergency safety
        for player in engine._current_state.players:
            result = await engine.perform_action(
                player.id, ActionType.VOTE_EMERGENCY, vote=True
            )
            assert result.success is True

        # Emergency safety should be active
        assert engine._current_state.emergency_safety_active is True

        # Continue with normal nomination and research
        director_id = engine._current_state.current_director.id
        eligible = [
            p.id
            for p in engine._current_state.players
            if p.id != director_id and not p.was_last_engineer
        ]

        await engine.perform_action(
            director_id, ActionType.NOMINATE, target_id=eligible[0]
        )

        # Vote yes on team
        for player in engine._current_state.players:
            await engine.perform_action(player.id, ActionType.VOTE_TEAM, vote=True)

        # Research phase
        assert engine._current_state.director_cards is not None
        paper_to_discard = engine._current_state.director_cards[0]
        await engine.perform_action(
            director_id, ActionType.DISCARD_PAPER, paper_id=paper_to_discard.id
        )

        # Publish paper - should have emergency safety modifier
        engineer_id = engine._current_state.nominated_engineer_id
        assert engine._current_state.engineer_cards is not None
        paper_to_publish = engine._current_state.engineer_cards[0]
        old_capability = engine._current_state.capability

        assert engineer_id is not None
        await engine.perform_action(
            engineer_id, ActionType.PUBLISH_PAPER, paper_id=paper_to_publish.id
        )

        # Capability gain should be reduced by 1 due to emergency safety
        expected_capability = old_capability + max(0, paper_to_publish.capability - 1)
        assert engine._current_state.capability == expected_capability
        assert engine._current_state.emergency_safety_active is False

    @pytest.mark.asyncio
    async def test_auto_publish_after_three_failures(self):
        """Test auto-publish mechanism after three failed proposals."""
        engine = GameEngine(database_url="sqlite:///:memory:")

        await engine.init_database()

        config = GameConfig(5, ["p1", "p2", "p3", "p4", "p5"], seed=42)
        await engine.create_game(config)
        assert engine._current_state is not None

        initial_deck_size = len(engine._current_state.deck)

        # Fail three proposals in a row
        for _failure in range(3):
            director_id = engine._current_state.current_director.id
            eligible = [
                p.id
                for p in engine._current_state.players
                if p.id != director_id and not p.was_last_engineer
            ]

            # Nominate
            await engine.perform_action(
                director_id, ActionType.NOMINATE, target_id=eligible[0]
            )

            # Vote fails
            for i, player in enumerate(engine._current_state.players):
                vote = i == 0  # Only first player votes yes
                await engine.perform_action(player.id, ActionType.VOTE_TEAM, vote=vote)

        # After third failure, should auto-publish
        assert engine._current_state.failed_proposals == 0  # Reset after auto-publish
        assert (
            len(engine._current_state.deck) == initial_deck_size - 1
        )  # One paper published
        assert len(engine._current_state.discard) == 1  # Paper in discard

        # All players should be eligible again
        eligible_after = [
            p.id for p in engine._current_state.players if not p.was_last_engineer
        ]
        assert len(eligible_after) == len(engine._current_state.players)


class TestWinConditions:
    """Test various win conditions in complete games."""

    @pytest.mark.asyncio
    async def test_safety_win_by_safety_15(self):
        """Test Safety win by reaching safety 15."""
        engine = GameEngine(database_url="sqlite:///:memory:")

        await engine.init_database()

        config = GameConfig(5, ["p1", "p2", "p3", "p4", "p5"], seed=42)
        await engine.create_game(config)
        assert engine._current_state is not None

        # Manually set state close to safety win
        engine._current_state.safety = 14
        engine._current_state.capability = 5

        # Engineer should publish high-safety paper to win
        engine._current_state.current_phase = Phase.RESEARCH
        engine._current_state.nominated_engineer_id = "p2"

        # Create high-safety paper
        from secret_agi.engine.models import Paper

        high_safety_paper = Paper("win_paper", 0, 2)  # +2 safety
        engine._current_state.engineer_cards = [high_safety_paper]

        result = await engine.perform_action(
            "p2", ActionType.PUBLISH_PAPER, paper_id="win_paper"
        )

        assert result.success is True
        assert engine._current_state.is_game_over is True
        assert Role.SAFETY in engine._current_state.winners
        assert engine._current_state.current_phase == Phase.GAME_OVER

    @pytest.mark.asyncio
    async def test_accelerationist_win_by_capability_gap(self):
        """Test Accelerationist/AGI win by capability-safety gap."""
        engine = GameEngine(database_url="sqlite:///:memory:")

        await engine.init_database()

        config = GameConfig(5, ["p1", "p2", "p3", "p4", "p5"], seed=42)
        await engine.create_game(config)
        assert engine._current_state is not None

        # Set state close to accelerationist win
        engine._current_state.capability = 8
        engine._current_state.safety = 2  # Gap = 6, triggers win

        # Any action that checks win conditions should trigger the win
        director_id = engine._current_state.current_director.id
        result = await engine.perform_action(director_id, ActionType.OBSERVE)

        assert result.success is True
        assert engine._current_state.is_game_over is True
        assert Role.ACCELERATIONIST in engine._current_state.winners
        assert Role.AGI in engine._current_state.winners

    @pytest.mark.asyncio
    async def test_deck_exhaustion_win(self):
        """Test win by deck exhaustion."""
        engine = GameEngine(database_url="sqlite:///:memory:")

        await engine.init_database()

        config = GameConfig(5, ["p1", "p2", "p3", "p4", "p5"], seed=42)
        await engine.create_game(config)
        assert engine._current_state is not None

        # Exhaust deck
        engine._current_state.deck = []
        engine._current_state.capability = 5
        engine._current_state.safety = 5  # Equal, so Safety wins

        # Any action should trigger win check
        result = await engine.perform_action(
            engine._current_state.players[0].id, ActionType.OBSERVE
        )

        assert result.success is True
        assert engine._current_state.is_game_over is True
        assert Role.SAFETY in engine._current_state.winners


class TestRandomPlayerIntegration:
    """Test integration with RandomPlayer implementations."""

    @pytest.mark.asyncio
    async def test_random_player_basic_functionality(self):
        """Test RandomPlayer can play basic actions."""
        engine = GameEngine(database_url="sqlite:///:memory:")

        await engine.init_database()

        config = GameConfig(5, ["p1", "p2", "p3", "p4", "p5"], seed=42)
        await engine.create_game(config)
        assert engine._current_state is not None

        # Create a random player
        player = RandomPlayer("p1", seed=42)
        player.set_game_engine(engine)

        # Player should be able to get game state
        state = player.observe_game_state()
        assert state is not None
        assert state.game_id == engine._current_state.game_id

        # Player should be able to get valid actions
        valid_actions = player.get_valid_actions()
        assert ActionType.OBSERVE in valid_actions

        # If player is director, should be able to nominate
        if state.current_director.id == "p1":
            assert ActionType.NOMINATE in valid_actions

            # Player should be able to choose an action
            action, params = player.choose_action(state, valid_actions)
            assert action in valid_actions

            # Player should be able to perform the action
            result = await player.perform_action(action, **params)
            assert result.success is True

    @pytest.mark.asyncio
    async def test_biased_random_player(self):
        """Test BiasedRandomPlayer functionality."""
        engine = GameEngine(database_url="sqlite:///:memory:")

        await engine.init_database()

        config = GameConfig(5, ["p1", "p2", "p3", "p4", "p5"], seed=42)
        await engine.create_game(config)
        assert engine._current_state is not None

        # Create biased random player
        player = BiasedRandomPlayer("p1", seed=42)
        player.set_game_engine(engine)

        # Initialize with game start
        state = player.observe_game_state()
        player.on_game_start(state)

        # Player should have role-based biases
        assert player.role is not None
        assert player.role_bias is not None

    @pytest.mark.asyncio
    async def test_multiple_random_players_game(self):
        """Test a game with multiple random players."""
        engine = GameEngine(database_url="sqlite:///:memory:")
        await engine.init_database()
        player_ids = ["p1", "p2", "p3", "p4", "p5"]
        config = GameConfig(5, player_ids, seed=42)
        await engine.create_game(config)
        assert engine._current_state is not None

        # Create random players for all positions
        players = {}
        for pid in player_ids:
            players[pid] = RandomPlayer(pid, seed=hash(pid))
            players[pid].set_game_engine(engine)

        # Initialize all players
        for player in players.values():
            state = player.observe_game_state()
            player.on_game_start(state)

        # Play a few turns with random players
        for _turn in range(10):
            if engine.is_game_over():
                break

            # Find a player with valid actions
            action_taken = False
            for player in players.values():
                state = player.observe_game_state()
                valid_actions = player.get_valid_actions()
                non_observe_actions = [
                    a for a in valid_actions if a != ActionType.OBSERVE
                ]

                if non_observe_actions:
                    action, params = player.choose_action(state, valid_actions)
                    result = await player.perform_action(action, **params)

                    if result.success:
                        # Notify all players of the update
                        for p in players.values():
                            p.on_game_update(result)
                        action_taken = True
                        break

            if not action_taken:
                break

        # Game should have progressed
        assert engine._current_state.turn_number > 0


class TestRandomGameCompletion:
    """Test that random games complete successfully."""

    @pytest.mark.asyncio
    async def test_single_random_game_completion(self):
        """Test that a single random game completes."""
        result = await run_random_game(
            player_count=5, seed=42, database_url="sqlite:///:memory:"
        )

        assert result["completed"] is True
        assert result["turns_taken"] > 0
        assert len(result["winners"]) > 0
        assert result["final_stats"]["is_game_over"] is True

    @pytest.mark.asyncio
    async def test_multiple_random_games_completion(self):
        """Test that multiple random games complete."""
        results = []

        for seed in range(10):
            result = await run_random_game(
                player_count=5, seed=seed, database_url="sqlite:///:memory:"
            )
            results.append(result)

        # Most games should complete (allowing for some edge cases in random gameplay)
        completed_count = sum(1 for r in results if r["completed"])
        assert completed_count >= 9  # At least 90% completion rate

        # Should have variety in winners
        all_winners = [tuple(sorted(r["winners"])) for r in results]
        unique_winners = set(all_winners)
        assert len(unique_winners) > 1  # Should have different outcomes

    @pytest.mark.asyncio
    async def test_different_player_count_completions(self):
        """Test game completion with different player counts."""
        for player_count in [5, 6, 7, 8, 9, 10]:
            result = await run_random_game(
                player_count=player_count, seed=42, database_url="sqlite:///:memory:"
            )

            assert result["completed"] is True
            assert result["final_stats"]["player_count"] == player_count
            assert result["turns_taken"] > 0

    @pytest.mark.asyncio
    async def test_large_batch_random_games(self):
        """Test a large batch of random games for stability."""
        completed_games = 0
        total_games = 50
        max_turns_seen = 0
        min_turns_seen = float("inf")

        for i in range(total_games):
            result = await run_random_game(
                player_count=5, seed=i, database_url="sqlite:///:memory:"
            )

            if result["completed"]:
                completed_games += 1
                turns = result["turns_taken"]
                max_turns_seen = max(max_turns_seen, turns)
                min_turns_seen = min(min_turns_seen, turns)

        # Reasonable completion rate expected (random gameplay can have edge cases)
        completion_rate = completed_games / total_games
        assert completion_rate >= 0.70  # At least 70% completion

        # Games should complete in reasonable time
        assert max_turns_seen < 500  # No extremely long games
        assert min_turns_seen > 0  # All games make progress

        print(
            f"Completed {completed_games}/{total_games} games ({completion_rate:.1%})"
        )
        print(f"Turn range: {min_turns_seen}-{max_turns_seen}")


class TestSystemStress:
    """Stress tests for the complete system."""

    @pytest.mark.asyncio
    async def test_rapid_game_creation(self):
        """Test creating many games rapidly."""
        engines = []

        for i in range(20):
            engine = GameEngine(database_url="sqlite:///:memory:")
            await engine.init_database()
            player_ids = [f"p{j}_{i}" for j in range(5)]
            config = GameConfig(5, player_ids, seed=i)
            await engine.create_game(config)
            assert engine._current_state is not None
            engines.append(engine)

        # All games should be created successfully
        assert len(engines) == 20
        for engine in engines:
            assert engine._current_state is not None
            assert not engine.is_game_over()

    @pytest.mark.asyncio
    async def test_long_running_simulation(self):
        """Test a long-running simulation doesn't break."""
        engine = GameEngine(database_url="sqlite:///:memory:")

        await engine.init_database()

        config = GameConfig(5, ["p1", "p2", "p3", "p4", "p5"], seed=42)
        await engine.create_game(config)
        assert engine._current_state is not None

        # Run for many turns
        result = await engine.simulate_to_completion(max_turns=1000)

        # Should either complete or hit turn limit gracefully
        assert result["turns_taken"] <= 1000
        if result["completed"]:
            assert engine.is_game_over()

    @pytest.mark.asyncio
    async def test_edge_case_scenarios(self):
        """Test various edge case scenarios."""
        # Game with minimum players
        result = await run_random_game(
            player_count=5, seed=1, database_url="sqlite:///:memory:"
        )
        assert result["completed"]

        # Game with maximum players
        result = await run_random_game(
            player_count=10, seed=1, database_url="sqlite:///:memory:"
        )
        assert result["completed"]

        # Multiple games with same seed (should be deterministic)
        result1 = await run_random_game(
            player_count=5, seed=123, database_url="sqlite:///:memory:"
        )
        result2 = await run_random_game(
            player_count=5, seed=123, database_url="sqlite:///:memory:"
        )

        # Results should be identical with same seed
        assert result1["winners"] == result2["winners"]
        assert result1["turns_taken"] == result2["turns_taken"]
