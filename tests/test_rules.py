"""Unit tests for the rules module."""

from secret_agi.engine.models import Allegiance, GameState, Paper, Phase, Player, Role
from secret_agi.engine.rules import GameRules


class TestWinConditions:
    """Test win condition checking."""

    def create_test_state(self, capability=0, safety=0, agi_alive=True):
        """Create a test game state."""
        players = [
            Player("p1", Role.SAFETY, Allegiance.SAFETY),
            Player("p2", Role.ACCELERATIONIST, Allegiance.ACCELERATION),
            Player("p3", Role.AGI, Allegiance.ACCELERATION, alive=agi_alive),
        ]

        state = GameState("test", players=players)
        state.capability = capability
        state.safety = safety
        # Add some papers to deck to avoid immediate deck exhaustion win unless we want it
        from secret_agi.engine.models import Paper

        state.deck = [Paper("p1", 1, 1), Paper("p2", 2, 0), Paper("p3", 0, 2)]
        return state

    def test_safety_win_capability_10(self):
        """Test Safety win when C=10 and S>=C."""
        state = self.create_test_state(capability=10, safety=10)
        game_over, winners = GameRules.check_win_conditions(state)

        assert game_over is True
        assert winners == [Role.SAFETY]

        # Test with safety > capability
        state = self.create_test_state(capability=10, safety=12)
        game_over, winners = GameRules.check_win_conditions(state)

        assert game_over is True
        assert winners == [Role.SAFETY]

        # Test with safety < capability (should not win)
        state = self.create_test_state(capability=10, safety=9)
        game_over, winners = GameRules.check_win_conditions(state)

        # This should NOT trigger a win since C-S = 1 < 6
        assert game_over is False
        assert winners == []

    def test_safety_win_safety_15(self):
        """Test Safety win when Safety reaches 15."""
        state = self.create_test_state(capability=8, safety=15)
        game_over, winners = GameRules.check_win_conditions(state)

        assert game_over is True
        assert winners == [Role.SAFETY]

    def test_safety_win_agi_eliminated(self):
        """Test Safety win when AGI is eliminated."""
        state = self.create_test_state(capability=5, safety=3, agi_alive=False)
        game_over, winners = GameRules.check_win_conditions(state)

        assert game_over is True
        assert winners == [Role.SAFETY]

    def test_accelerationist_win_capability_15(self):
        """Test Accelerationist/AGI win when C=15 and S<10."""
        state = self.create_test_state(capability=15, safety=9)
        game_over, winners = GameRules.check_win_conditions(state)

        assert game_over is True
        assert winners == [Role.ACCELERATIONIST, Role.AGI]

        # Test with safety >= 10 (should not win this way)
        state = self.create_test_state(capability=15, safety=10)
        game_over, winners = GameRules.check_win_conditions(state)

        # Should NOT win: C>=15 but S>=10, and C-S=5 < 6
        assert game_over is False
        assert winners == []

    def test_accelerationist_win_capability_gap(self):
        """Test Accelerationist/AGI win when C-S >= 6."""
        state = self.create_test_state(capability=10, safety=4)
        game_over, winners = GameRules.check_win_conditions(state)

        assert game_over is True
        assert winners == [Role.ACCELERATIONIST, Role.AGI]

        # Test edge case
        state = self.create_test_state(capability=8, safety=2)
        game_over, winners = GameRules.check_win_conditions(state)

        assert game_over is True
        assert winners == [Role.ACCELERATIONIST, Role.AGI]

    def test_agi_engineer_win(self):
        """Test AGI win when elected Engineer with C>=8."""
        state = self.create_test_state(capability=8, safety=5)
        state.current_phase = Phase.RESEARCH
        state.nominated_engineer_id = "p3"  # AGI player

        game_over, winners = GameRules.check_win_conditions(state)

        assert game_over is True
        assert winners == [Role.ACCELERATIONIST, Role.AGI]

        # Test with C < 8 (should not win)
        state.capability = 7
        game_over, winners = GameRules.check_win_conditions(state)

        assert game_over is False

    def test_deck_exhaustion(self):
        """Test deck exhaustion win conditions."""
        state = self.create_test_state(capability=5, safety=5)
        state.deck = []  # Empty deck

        # Safety wins if S >= C
        game_over, winners = GameRules.check_win_conditions(state)
        assert game_over is True
        assert winners == [Role.SAFETY]

        # Accelerationists win if S < C
        state.safety = 4
        game_over, winners = GameRules.check_win_conditions(state)
        assert game_over is True
        assert winners == [Role.ACCELERATIONIST, Role.AGI]

    def test_no_win_condition(self):
        """Test when no win condition is met."""
        state = self.create_test_state(capability=5, safety=4)
        state.deck = [Paper("p1", 1, 1)]  # Non-empty deck

        game_over, winners = GameRules.check_win_conditions(state)

        assert game_over is False
        assert winners == []


class TestEmergencySafety:
    """Test emergency safety mechanics."""

    def test_emergency_safety_conditions(self):
        """Test emergency safety trigger conditions."""
        state = GameState("test")

        # Test various capability-safety differences
        state.capability, state.safety = 5, 1  # diff = 4
        assert GameRules.check_emergency_safety_conditions(state) is True

        state.capability, state.safety = 8, 3  # diff = 5
        assert GameRules.check_emergency_safety_conditions(state) is True

        state.capability, state.safety = 6, 3  # diff = 3
        assert GameRules.check_emergency_safety_conditions(state) is False

        state.capability, state.safety = 10, 4  # diff = 6
        assert GameRules.check_emergency_safety_conditions(state) is False


class TestEngineerEligibility:
    """Test engineer eligibility rules."""

    def test_get_eligible_engineers(self):
        """Test getting eligible engineers."""
        players = [
            Player(
                "p1",
                Role.SAFETY,
                Allegiance.SAFETY,
                alive=True,
                was_last_engineer=False,
            ),
            Player(
                "p2",
                Role.ACCELERATIONIST,
                Allegiance.ACCELERATION,
                alive=True,
                was_last_engineer=True,
            ),
            Player(
                "p3",
                Role.AGI,
                Allegiance.ACCELERATION,
                alive=False,
                was_last_engineer=False,
            ),
            Player(
                "p4",
                Role.SAFETY,
                Allegiance.SAFETY,
                alive=True,
                was_last_engineer=False,
            ),
        ]

        state = GameState("test", players=players)
        eligible = GameRules.get_eligible_engineers(state)

        # Should include p1 and p4 (alive and not last engineer)
        # Should exclude p2 (was last engineer) and p3 (dead)
        assert set(eligible) == {"p1", "p4"}

    def test_reset_engineer_eligibility(self):
        """Test resetting engineer eligibility."""
        players = [
            Player("p1", Role.SAFETY, Allegiance.SAFETY, was_last_engineer=True),
            Player(
                "p2",
                Role.ACCELERATIONIST,
                Allegiance.ACCELERATION,
                was_last_engineer=True,
            ),
        ]

        state = GameState("test", players=players)
        GameRules.reset_engineer_eligibility(state)

        for player in state.players:
            assert player.was_last_engineer is False


class TestPowerActivation:
    """Test power activation logic."""

    def test_check_powers_triggered(self):
        """Test power trigger detection."""
        # Test 5-player game (no C=3, C=11 powers)
        powers = GameRules.check_powers_triggered(5, 7, 5)
        assert powers == [6]

        powers = GameRules.check_powers_triggered(8, 13, 5)
        assert powers == [9, 10, 12]

        # Test 10-player game (includes C=3, C=11 powers)
        powers = GameRules.check_powers_triggered(2, 4, 10)
        assert powers == [3]

        powers = GameRules.check_powers_triggered(9, 12, 10)
        assert powers == [10, 11, 12]

        # Test no powers triggered
        powers = GameRules.check_powers_triggered(5, 5, 7)
        assert powers == []


class TestVotingMechanics:
    """Test voting validation and results."""

    def create_voting_state(self):
        """Create state with 3 alive players for voting tests."""
        players = [
            Player("p1", Role.SAFETY, Allegiance.SAFETY, alive=True),
            Player("p2", Role.ACCELERATIONIST, Allegiance.ACCELERATION, alive=True),
            Player("p3", Role.AGI, Allegiance.ACCELERATION, alive=False),
            Player("p4", Role.SAFETY, Allegiance.SAFETY, alive=True),
        ]
        state = GameState("test", players=players)
        # Add some papers to deck to avoid immediate deck exhaustion win
        from secret_agi.engine.models import Paper

        state.deck = [Paper("p1", 1, 1), Paper("p2", 2, 0), Paper("p3", 0, 2)]
        return state

    def test_team_vote_validation(self):
        """Test team vote completion validation."""
        state = self.create_voting_state()

        # No votes yet
        assert GameRules.validate_team_vote_complete(state) is False

        # Partial votes
        state.team_votes = {"p1": True, "p2": False}
        assert GameRules.validate_team_vote_complete(state) is False

        # All alive players voted
        state.team_votes = {"p1": True, "p2": False, "p4": True}
        assert GameRules.validate_team_vote_complete(state) is True

        # Including dead player vote (shouldn't count) - only alive players p1, p2, p4 need to vote
        state.team_votes = {"p1": True, "p2": False, "p3": True, "p4": True}
        assert GameRules.validate_team_vote_complete(state) is True

    def test_team_vote_results(self):
        """Test team vote result calculation."""
        state = self.create_voting_state()

        # Majority yes (2/3)
        state.team_votes = {"p1": True, "p2": True, "p4": False}
        assert GameRules.calculate_team_vote_result(state) is True

        # Majority no (1/3)
        state.team_votes = {"p1": True, "p2": False, "p4": False}
        assert GameRules.calculate_team_vote_result(state) is False

        # Tie (should fail)
        players = [
            Player("p1", Role.SAFETY, Allegiance.SAFETY, alive=True),
            Player("p2", Role.ACCELERATIONIST, Allegiance.ACCELERATION, alive=True),
        ]
        state = GameState("test", players=players)
        state.team_votes = {"p1": True, "p2": False}
        assert GameRules.calculate_team_vote_result(state) is False


class TestFailedProposals:
    """Test failed proposal mechanics."""

    def test_failed_proposal_management(self):
        """Test failed proposal counter management."""
        state = GameState("test")

        assert state.failed_proposals == 0
        assert GameRules.auto_publish_required(state) is False

        GameRules.increment_failed_proposals(state)
        assert state.failed_proposals == 1

        GameRules.increment_failed_proposals(state)
        assert state.failed_proposals == 2

        GameRules.increment_failed_proposals(state)
        assert state.failed_proposals == 3
        assert GameRules.auto_publish_required(state) is True

        GameRules.reset_failed_proposals(state)
        assert state.failed_proposals == 0

    def test_auto_publish_paper(self):
        """Test auto-publishing paper mechanism."""
        state = GameState("test")
        state.deck = [
            Paper("p1", 2, 1),
            Paper("p2", 1, 2),
        ]
        state.failed_proposals = 3
        state.emergency_safety_active = True

        GameRules.auto_publish_paper(state)

        # Check paper was published with emergency safety modifier
        assert state.capability == 1  # 2 - 1 (emergency safety)
        assert state.safety == 1
        assert len(state.deck) == 1
        assert len(state.discard) == 1
        assert state.failed_proposals == 0
        assert state.emergency_safety_active is False

        # Check event was added
        assert len(state.events) == 1
        event = state.events[0]
        assert event.data["auto_published"] is True
        assert event.data["capability_gain"] == 1


class TestPaperPublication:
    """Test paper publication mechanics."""

    def test_publish_paper(self):
        """Test paper publication."""
        state = GameState("test")
        state.capability = 5
        state.safety = 3
        state.engineer_cards = [
            Paper("p1", 2, 1),
            Paper("p2", 1, 3),
        ]

        # Find engineer
        engineer = Player("eng1", Role.SAFETY, Allegiance.SAFETY)
        state.players = [engineer]

        GameRules.publish_paper(state, "p1", "eng1")

        # Check board state updated
        assert state.capability == 7  # 5 + 2
        assert state.safety == 4  # 3 + 1

        # Check cards moved to discard
        assert len(state.discard) == 2  # Both engineer cards
        assert state.engineer_cards is None

        # Check engineer marked as last
        assert engineer.was_last_engineer is True

        # Check events added (paper published + power triggered at C=6)
        assert len(state.events) >= 1
        paper_events = [e for e in state.events if e.type.value == "paper_published"]
        assert len(paper_events) == 1
        event = paper_events[0]
        assert event.data["auto_published"] is False

    def test_publish_with_emergency_safety(self):
        """Test paper publication with emergency safety active."""
        state = GameState("test")
        state.capability = 5
        state.safety = 3
        state.emergency_safety_active = True
        state.engineer_cards = [Paper("p1", 3, 1)]

        engineer = Player("eng1", Role.SAFETY, Allegiance.SAFETY)
        state.players = [engineer]

        GameRules.publish_paper(state, "p1", "eng1")

        # Check emergency safety modifier applied
        assert state.capability == 7  # 5 + (3-1)
        assert state.safety == 4  # 3 + 1
        assert state.emergency_safety_active is False


class TestPowerActions:
    """Test power-related actions."""

    def test_eliminate_player(self):
        """Test player elimination."""
        players = [
            Player("p1", Role.SAFETY, Allegiance.SAFETY, alive=True),
            Player("p2", Role.AGI, Allegiance.ACCELERATION, alive=True),
        ]
        state = GameState("test", players=players)

        GameRules.eliminate_player(state, "p2")

        player = state.get_player_by_id("p2")
        assert player is not None
        assert player.alive is False

        # Check event was added
        assert len(state.events) == 1
        event = state.events[0]
        assert event.data["player_id"] == "p2"
        assert event.data["role"] == "AGI"

    def test_view_allegiance(self):
        """Test allegiance viewing."""
        players = [
            Player("p1", Role.SAFETY, Allegiance.SAFETY),
            Player("p2", Role.AGI, Allegiance.ACCELERATION),
        ]
        state = GameState("test", players=players)

        GameRules.view_allegiance(state, "p1", "p2")

        # Check allegiance was recorded
        assert "p1" in state.viewed_allegiances
        assert "p2" in state.viewed_allegiances["p1"]
        assert state.viewed_allegiances["p1"]["p2"] == Allegiance.ACCELERATION

        # Check event was added
        assert len(state.events) == 1
        event = state.events[0]
        assert event.player_id == "p1"
        assert event.data["target_id"] == "p2"
        assert event.data["allegiance"] == "Acceleration"

    def test_set_next_director(self):
        """Test setting next director."""
        players = [
            Player("p1", Role.SAFETY, Allegiance.SAFETY, alive=True),
            Player("p2", Role.ACCELERATIONIST, Allegiance.ACCELERATION, alive=True),
            Player("p3", Role.AGI, Allegiance.ACCELERATION, alive=True),
        ]
        state = GameState("test", players=players)
        state.current_director_index = 0

        GameRules.set_next_director(state, "p3")

        assert state.current_director_index == 2

        # Check event was added
        assert len(state.events) == 1
        event = state.events[0]
        assert event.data["new_director_id"] == "p3"
