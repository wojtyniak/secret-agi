"""Unit tests for the actions module."""

from secret_agi.engine.actions import ActionProcessor, ActionValidator
from secret_agi.engine.models import (
    ActionType,
    Allegiance,
    GameState,
    Paper,
    Phase,
    Player,
    Role,
)


class TestActionValidator:
    """Test action validation logic."""

    def create_test_state(self, phase=Phase.TEAM_PROPOSAL):
        """Create a test game state."""
        players = [
            Player("director", Role.SAFETY, Allegiance.SAFETY, alive=True),
            Player(
                "player2", Role.ACCELERATIONIST, Allegiance.ACCELERATION, alive=True
            ),
            Player("player3", Role.AGI, Allegiance.ACCELERATION, alive=True),
        ]

        state = GameState("test", players=players)
        state.current_phase = phase
        state.current_director_index = 0  # director is current director
        # Add some papers to deck to avoid immediate deck exhaustion win
        from secret_agi.engine.models import Paper

        state.deck = [Paper("p1", 1, 1), Paper("p2", 2, 0), Paper("p3", 0, 2)]
        return state

    def test_dead_player_validation(self):
        """Test that dead players cannot perform actions."""
        state = self.create_test_state()
        state.players[1].alive = False

        valid, error = ActionValidator.validate_action(
            state, "player2", ActionType.VOTE_TEAM, vote=True
        )

        assert valid is False
        assert error is not None and "eliminated" in error

    def test_nonexistent_player_validation(self):
        """Test validation for nonexistent player."""
        state = self.create_test_state()

        valid, error = ActionValidator.validate_action(
            state, "nonexistent", ActionType.OBSERVE
        )

        assert valid is False
        assert error is not None and "not found" in error

    def test_observe_always_valid(self):
        """Test that observe is always valid for alive players."""
        state = self.create_test_state()

        for player in state.players:
            valid, error = ActionValidator.validate_action(
                state, player.id, ActionType.OBSERVE
            )
            assert valid is True
            assert error is None

    def test_game_over_validation(self):
        """Test that no actions (except observe) are valid when game is over."""
        state = self.create_test_state()
        state.current_phase = Phase.GAME_OVER

        valid, error = ActionValidator.validate_action(
            state, "director", ActionType.NOMINATE, target_id="player2"
        )

        assert valid is False
        assert error is not None and "Game is over" in error


class TestTeamProposalValidation:
    """Test action validation during team proposal phase."""

    def create_team_proposal_state(self):
        """Create state in team proposal phase."""
        players = [
            Player("director", Role.SAFETY, Allegiance.SAFETY, alive=True),
            Player(
                "player2",
                Role.ACCELERATIONIST,
                Allegiance.ACCELERATION,
                alive=True,
                was_last_engineer=True,
            ),
            Player("player3", Role.AGI, Allegiance.ACCELERATION, alive=True),
        ]

        state = GameState("test", players=players)
        state.current_phase = Phase.TEAM_PROPOSAL
        state.current_director_index = 0
        # Add some papers to deck to avoid immediate deck exhaustion win
        from secret_agi.engine.models import Paper

        state.deck = [Paper("p1", 1, 1), Paper("p2", 2, 0), Paper("p3", 0, 2)]
        return state

    def test_nominate_validation(self):
        """Test nomination validation."""
        state = self.create_team_proposal_state()

        # Valid nomination
        valid, error = ActionValidator.validate_action(
            state, "director", ActionType.NOMINATE, target_id="player3"
        )
        assert valid is True

        # Non-director cannot nominate
        valid, error = ActionValidator.validate_action(
            state, "player2", ActionType.NOMINATE, target_id="player3"
        )
        assert valid is False
        assert error is not None and "Only the director" in error

        # Cannot nominate ineligible player
        valid, error = ActionValidator.validate_action(
            state, "director", ActionType.NOMINATE, target_id="player2"
        )
        assert valid is False
        assert error is not None and "not eligible" in error

        # Cannot nominate twice
        state.nominated_engineer_id = "player3"
        valid, error = ActionValidator.validate_action(
            state, "director", ActionType.NOMINATE, target_id="player3"
        )
        assert valid is False
        assert error is not None and "already nominated" in error

    def test_emergency_safety_validation(self):
        """Test emergency safety call validation."""
        state = self.create_team_proposal_state()

        # Not triggered yet
        state.capability = 5
        state.safety = 2  # diff = 3, not enough
        valid, error = ActionValidator.validate_action(
            state, "director", ActionType.CALL_EMERGENCY_SAFETY
        )
        assert valid is False
        assert error is not None and "conditions not met" in error

        # Triggered
        state.capability = 6
        state.safety = 2  # diff = 4, triggers emergency
        valid, error = ActionValidator.validate_action(
            state, "director", ActionType.CALL_EMERGENCY_SAFETY
        )
        assert valid is True

        # Already called
        state.emergency_safety_called = True
        valid, error = ActionValidator.validate_action(
            state, "director", ActionType.CALL_EMERGENCY_SAFETY
        )
        assert valid is False
        assert error is not None and "already called" in error

    def test_vote_emergency_validation(self):
        """Test emergency vote validation."""
        state = self.create_team_proposal_state()

        # No emergency called
        valid, error = ActionValidator.validate_action(
            state, "director", ActionType.VOTE_EMERGENCY, vote=True
        )
        assert valid is False
        assert error is not None and "No emergency safety vote" in error

        # Emergency called
        state.emergency_safety_called = True
        valid, error = ActionValidator.validate_action(
            state, "director", ActionType.VOTE_EMERGENCY, vote=True
        )
        assert valid is True

        # Already voted
        state.emergency_votes["director"] = True
        valid, error = ActionValidator.validate_action(
            state, "director", ActionType.VOTE_EMERGENCY, vote=False
        )
        assert valid is False
        assert error is not None and "Already voted" in error

    def test_vote_team_validation(self):
        """Test team vote validation."""
        state = self.create_team_proposal_state()

        # No engineer nominated
        valid, error = ActionValidator.validate_action(
            state, "director", ActionType.VOTE_TEAM, vote=True
        )
        assert valid is False
        assert error is not None and "No engineer nominated" in error

        # Engineer nominated
        state.nominated_engineer_id = "player3"
        valid, error = ActionValidator.validate_action(
            state, "director", ActionType.VOTE_TEAM, vote=True
        )
        assert valid is True

        # Already voted
        state.team_votes["director"] = True
        valid, error = ActionValidator.validate_action(
            state, "director", ActionType.VOTE_TEAM, vote=False
        )
        assert valid is False
        assert error is not None and "Already voted" in error

        # Emergency safety must be resolved first
        state.team_votes = {}  # Reset votes
        state.emergency_safety_called = True
        state.emergency_votes = {"director": True}  # Incomplete emergency vote
        valid, error = ActionValidator.validate_action(
            state, "director", ActionType.VOTE_TEAM, vote=True
        )
        assert valid is False
        assert error is not None and "emergency safety vote first" in error


class TestResearchPhaseValidation:
    """Test action validation during research phase."""

    def create_research_state(self):
        """Create state in research phase."""
        players = [
            Player("director", Role.SAFETY, Allegiance.SAFETY, alive=True),
            Player(
                "engineer", Role.ACCELERATIONIST, Allegiance.ACCELERATION, alive=True
            ),
            Player("player3", Role.AGI, Allegiance.ACCELERATION, alive=True),
        ]

        state = GameState("test", players=players)
        state.current_phase = Phase.RESEARCH
        state.current_director_index = 0
        state.nominated_engineer_id = "engineer"
        # Add some papers to deck to avoid immediate deck exhaustion win
        from secret_agi.engine.models import Paper

        state.deck = [Paper("p1", 1, 1), Paper("p2", 2, 0), Paper("p3", 0, 2)]
        return state

    def test_discard_paper_validation(self):
        """Test paper discard validation."""
        state = self.create_research_state()

        # No cards to discard
        valid, error = ActionValidator.validate_action(
            state, "director", ActionType.DISCARD_PAPER, paper_id="p1"
        )
        assert valid is False
        assert error is not None and "No papers to discard" in error

        # Has cards
        state.director_cards = [Paper("p1", 1, 1), Paper("p2", 2, 0)]
        valid, error = ActionValidator.validate_action(
            state, "director", ActionType.DISCARD_PAPER, paper_id="p1"
        )
        assert valid is True

        # Non-director cannot discard
        valid, error = ActionValidator.validate_action(
            state, "engineer", ActionType.DISCARD_PAPER, paper_id="p1"
        )
        assert valid is False
        assert error is not None and "Only the director" in error

        # Paper not in hand
        valid, error = ActionValidator.validate_action(
            state, "director", ActionType.DISCARD_PAPER, paper_id="p3"
        )
        assert valid is False
        assert error is not None and "not in director's hand" in error

    def test_publish_paper_validation(self):
        """Test paper publish validation."""
        state = self.create_research_state()

        # No cards to publish
        valid, error = ActionValidator.validate_action(
            state, "engineer", ActionType.PUBLISH_PAPER, paper_id="p1"
        )
        assert valid is False
        assert error is not None and "No papers to publish" in error

        # Has cards
        state.engineer_cards = [Paper("p1", 1, 1), Paper("p2", 2, 0)]
        valid, error = ActionValidator.validate_action(
            state, "engineer", ActionType.PUBLISH_PAPER, paper_id="p1"
        )
        assert valid is True

        # Non-engineer cannot publish
        valid, error = ActionValidator.validate_action(
            state, "director", ActionType.PUBLISH_PAPER, paper_id="p1"
        )
        assert valid is False
        assert error is not None and "Only the engineer" in error

        # Paper not in hand
        valid, error = ActionValidator.validate_action(
            state, "engineer", ActionType.PUBLISH_PAPER, paper_id="p3"
        )
        assert valid is False
        assert error is not None and "not in engineer's hand" in error

    def test_veto_validation(self):
        """Test veto validation."""
        state = self.create_research_state()

        # Veto not unlocked
        valid, error = ActionValidator.validate_action(
            state, "engineer", ActionType.DECLARE_VETO
        )
        assert valid is False
        assert error is not None and "not unlocked" in error

        # Veto unlocked
        state.veto_unlocked = True
        state.engineer_cards = [Paper("p1", 1, 1)]
        valid, error = ActionValidator.validate_action(
            state, "engineer", ActionType.DECLARE_VETO
        )
        assert valid is True

        # Non-engineer cannot veto
        valid, error = ActionValidator.validate_action(
            state, "director", ActionType.DECLARE_VETO
        )
        assert valid is False
        assert error is not None and "Only the engineer" in error


class TestValidActionsGeneration:
    """Test generation of valid actions for players."""

    def create_test_state(self):
        """Create a test state."""
        players = [
            Player("director", Role.SAFETY, Allegiance.SAFETY, alive=True),
            Player(
                "player2", Role.ACCELERATIONIST, Allegiance.ACCELERATION, alive=True
            ),
            Player("player3", Role.AGI, Allegiance.ACCELERATION, alive=False),
        ]

        state = GameState("test", players=players)
        state.current_director_index = 0
        # Add some papers to deck to avoid immediate deck exhaustion win
        from secret_agi.engine.models import Paper

        state.deck = [Paper("p1", 1, 1), Paper("p2", 2, 0), Paper("p3", 0, 2)]
        return state

    def test_team_proposal_valid_actions(self):
        """Test valid actions during team proposal."""
        state = self.create_test_state()
        state.current_phase = Phase.TEAM_PROPOSAL

        # Director can nominate
        actions = ActionValidator.get_valid_actions(state, "director")
        assert ActionType.OBSERVE in actions
        assert ActionType.NOMINATE in actions

        # Non-director cannot nominate
        actions = ActionValidator.get_valid_actions(state, "player2")
        assert ActionType.OBSERVE in actions
        assert ActionType.NOMINATE not in actions

        # After nomination, can vote
        state.nominated_engineer_id = "player2"
        actions = ActionValidator.get_valid_actions(state, "director")
        assert ActionType.VOTE_TEAM in actions
        assert ActionType.NOMINATE not in actions  # Already nominated

        # Emergency safety conditions
        state.capability = 6
        state.safety = 1  # diff = 5, triggers emergency
        actions = ActionValidator.get_valid_actions(state, "player2")
        assert ActionType.CALL_EMERGENCY_SAFETY in actions

        # After emergency called
        state.emergency_safety_called = True
        actions = ActionValidator.get_valid_actions(state, "player2")
        assert ActionType.VOTE_EMERGENCY in actions
        assert ActionType.CALL_EMERGENCY_SAFETY not in actions

    def test_research_valid_actions(self):
        """Test valid actions during research."""
        state = self.create_test_state()
        state.current_phase = Phase.RESEARCH
        state.nominated_engineer_id = "player2"

        # Director with cards can discard
        state.director_cards = [Paper("p1", 1, 1)]
        actions = ActionValidator.get_valid_actions(state, "director")
        assert ActionType.DISCARD_PAPER in actions

        # Engineer with cards can publish (after director discards)
        state.director_cards = None
        state.engineer_cards = [Paper("p1", 1, 1)]
        actions = ActionValidator.get_valid_actions(state, "player2")
        assert ActionType.PUBLISH_PAPER in actions

        # With veto unlocked
        state.veto_unlocked = True
        actions = ActionValidator.get_valid_actions(state, "player2")
        assert ActionType.DECLARE_VETO in actions

    def test_dead_player_valid_actions(self):
        """Test that dead players only have observe."""
        state = self.create_test_state()

        actions = ActionValidator.get_valid_actions(state, "player3")  # Dead player
        assert actions == [ActionType.OBSERVE]


class TestActionProcessor:
    """Test action processing logic."""

    def create_test_state(self):
        """Create a test state for processing."""
        players = [
            Player("director", Role.SAFETY, Allegiance.SAFETY, alive=True),
            Player(
                "player2", Role.ACCELERATIONIST, Allegiance.ACCELERATION, alive=True
            ),
            Player("player3", Role.AGI, Allegiance.ACCELERATION, alive=True),
        ]

        state = GameState("test", players=players)
        state.current_director_index = 0
        # Add enough papers to deck to avoid immediate deck exhaustion win after drawing 3 cards
        from secret_agi.engine.models import Paper

        state.deck = [
            Paper("p1", 1, 1),
            Paper("p2", 2, 0),
            Paper("p3", 0, 2),
            Paper("p4", 1, 1),
            Paper("p5", 2, 0),
            Paper("p6", 0, 2),
            Paper("p7", 1, 1),
            Paper("p8", 2, 0),
            Paper("p9", 0, 2),
        ]
        return state

    def test_observe_action(self):
        """Test observe action processing."""
        state = self.create_test_state()

        result = ActionProcessor.process_action(state, "director", ActionType.OBSERVE)

        assert result.success is True
        assert result.error is None
        assert len(result.events) == 1
        assert result.events[0].data["action"] == "observe"

    def test_nominate_action(self):
        """Test nomination processing."""
        state = self.create_test_state()
        state.current_phase = Phase.TEAM_PROPOSAL

        result = ActionProcessor.process_action(
            state, "director", ActionType.NOMINATE, target_id="player2"
        )

        assert result.success is True
        assert state.nominated_engineer_id == "player2"
        assert len(result.events) == 1
        assert result.events[0].data["target_id"] == "player2"

    def test_vote_team_success(self):
        """Test successful team vote processing."""
        state = self.create_test_state()
        state.current_phase = Phase.TEAM_PROPOSAL
        state.nominated_engineer_id = "player2"

        # All players vote yes
        ActionProcessor.process_action(
            state, "director", ActionType.VOTE_TEAM, vote=True
        )
        ActionProcessor.process_action(
            state, "player2", ActionType.VOTE_TEAM, vote=True
        )
        result = ActionProcessor.process_action(
            state, "player3", ActionType.VOTE_TEAM, vote=True
        )

        assert result.success is True
        assert state.current_phase == Phase.RESEARCH
        assert state.director_cards is not None
        assert len(state.director_cards) <= 3

    def test_vote_team_failure(self):
        """Test failed team vote processing."""
        state = self.create_test_state()
        state.current_phase = Phase.TEAM_PROPOSAL
        state.nominated_engineer_id = "player2"
        state.deck = [Paper("p1", 1, 1), Paper("p2", 2, 0)]

        # Majority vote no
        ActionProcessor.process_action(
            state, "director", ActionType.VOTE_TEAM, vote=True
        )
        ActionProcessor.process_action(
            state, "player2", ActionType.VOTE_TEAM, vote=False
        )
        result = ActionProcessor.process_action(
            state, "player3", ActionType.VOTE_TEAM, vote=False
        )

        assert result.success is True
        assert state.current_phase == Phase.TEAM_PROPOSAL  # Back to proposal
        assert state.failed_proposals == 1
        assert state.current_director_index != 0  # Director advanced

    def test_discard_paper(self):
        """Test paper discard processing."""
        state = self.create_test_state()
        state.current_phase = Phase.RESEARCH
        state.director_cards = [Paper("p1", 1, 1), Paper("p2", 2, 0), Paper("p3", 0, 2)]

        result = ActionProcessor.process_action(
            state, "director", ActionType.DISCARD_PAPER, paper_id="p2"
        )

        assert result.success is True
        assert len(state.discard) == 1
        assert state.discard[0].id == "p2"
        assert state.engineer_cards is not None
        assert len(state.engineer_cards) == 2
        assert state.director_cards is None

    def test_publish_paper(self):
        """Test paper publication processing."""
        state = self.create_test_state()
        state.current_phase = Phase.RESEARCH
        state.nominated_engineer_id = "player2"
        state.engineer_cards = [Paper("p1", 2, 1), Paper("p2", 1, 2)]
        state.capability = 3
        state.safety = 2

        result = ActionProcessor.process_action(
            state, "player2", ActionType.PUBLISH_PAPER, paper_id="p1"
        )

        assert result.success is True
        assert state.capability == 5  # 3 + 2
        assert state.safety == 3  # 2 + 1
        assert len(state.discard) == 2  # Both engineer cards discarded
        assert state.engineer_cards is None

        # Check engineer marked as last
        engineer = state.get_player_by_id("player2")
        assert engineer.was_last_engineer is True

    def test_invalid_action_processing(self):
        """Test processing of invalid actions."""
        state = self.create_test_state()
        state.current_phase = Phase.TEAM_PROPOSAL

        # Try to nominate without being director
        result = ActionProcessor.process_action(
            state, "player2", ActionType.NOMINATE, target_id="player3"
        )

        assert result.success is False
        assert result.error is not None and "Only the director" in result.error
        assert result.game_state == state  # State unchanged

    def test_win_condition_check(self):
        """Test win condition checking after actions."""
        state = self.create_test_state()
        state.current_phase = Phase.RESEARCH
        state.nominated_engineer_id = "player2"
        state.engineer_cards = [Paper("p1", 10, 1)]  # High capability paper
        state.capability = 5
        state.safety = 15  # Safety already at win condition

        result = ActionProcessor.process_action(
            state, "player2", ActionType.PUBLISH_PAPER, paper_id="p1"
        )

        assert result.success is True
        assert state.is_game_over is True
        assert state.current_phase == Phase.GAME_OVER
        assert Role.SAFETY in state.winners

        # Check game end event was added
        game_end_events = [e for e in result.events if e.type.value == "game_ended"]
        assert len(game_end_events) == 1
