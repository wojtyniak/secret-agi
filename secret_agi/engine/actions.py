"""Action validation and processing for Secret AGI game engine."""

from typing import Any

from .models import ActionType, EventType, GameState, GameUpdate, Phase, Player
from .rules import GameRules


class ActionValidator:
    """Validates player actions against current game state."""

    @staticmethod
    def validate_action(
        state: GameState, player_id: str, action: ActionType, **kwargs: Any
    ) -> tuple[bool, str | None]:
        """
        Validate if a player can perform an action.
        Returns (is_valid, error_message).
        """
        player = state.get_player_by_id(player_id)
        if not player:
            return False, f"Player {player_id} not found"

        if not player.alive:
            return False, f"Player {player_id} is eliminated"

        # Always allow observe
        if action == ActionType.OBSERVE:
            return True, None

        # Phase-specific validations
        if state.current_phase == Phase.TEAM_PROPOSAL:
            return ActionValidator._validate_team_proposal_action(
                state, player, action, **kwargs
            )
        elif state.current_phase == Phase.RESEARCH:
            return ActionValidator._validate_research_action(
                state, player, action, **kwargs
            )
        else:  # Phase.GAME_OVER
            return False, "Game is over"

    @staticmethod
    def _validate_team_proposal_action(
        state: GameState, player: Player, action: ActionType, **kwargs: Any
    ) -> tuple[bool, str | None]:
        """Validate actions during team proposal phase."""

        if action == ActionType.NOMINATE:
            # Only director can nominate
            if player.id != state.current_director.id:
                return False, "Only the director can nominate"

            # Must have target
            target_id = kwargs.get("target_id")
            if not target_id:
                return False, "Must specify target player"

            # Target must be eligible
            eligible = GameRules.get_eligible_engineers(state)
            if target_id not in eligible:
                return False, f"Player {target_id} is not eligible to be engineer"

            # Can't nominate if already nominated someone this round
            if state.nominated_engineer_id:
                return False, "Engineer already nominated for this round"

            return True, None

        elif action == ActionType.CALL_EMERGENCY_SAFETY:
            # Check if emergency safety conditions are met
            if not GameRules.check_emergency_safety_conditions(state):
                return False, "Emergency safety conditions not met"

            # Check if already called this round
            if state.emergency_safety_called:
                return False, "Emergency safety already called this round"

            return True, None

        elif action == ActionType.VOTE_EMERGENCY:
            # Must have emergency safety called
            if not state.emergency_safety_called:
                return False, "No emergency safety vote in progress"

            # Can't vote twice
            if player.id in state.emergency_votes:
                return False, "Already voted on emergency safety"

            return True, None

        elif action == ActionType.VOTE_TEAM:
            # Must have nominated engineer
            if not state.nominated_engineer_id:
                return False, "No engineer nominated yet"

            # Emergency safety must be resolved first
            if (
                state.emergency_safety_called
                and not GameRules.validate_emergency_vote_complete(state)
            ):
                return False, "Must complete emergency safety vote first"

            # Can't vote twice
            if player.id in state.team_votes:
                return False, "Already voted on team"

            return True, None

        return False, f"Action {action} not valid during team proposal phase"

    @staticmethod
    def _validate_research_action(
        state: GameState, player: Player, action: ActionType, **kwargs: Any
    ) -> tuple[bool, str | None]:
        """Validate actions during research phase."""

        if action == ActionType.DISCARD_PAPER:
            # Only director can discard
            if player.id != state.current_director.id:
                return False, "Only the director can discard papers"

            # Must have director cards
            if not state.director_cards:
                return False, "No papers to discard"

            # Must specify paper
            paper_id = kwargs.get("paper_id")
            if not paper_id:
                return False, "Must specify paper to discard"

            # Paper must be in director's hand
            if not any(p.id == paper_id for p in state.director_cards):
                return False, "Paper not in director's hand"

            return True, None

        elif action == ActionType.DECLARE_VETO:
            # Only engineer can declare veto
            if player.id != state.nominated_engineer_id:
                return False, "Only the engineer can declare veto"

            # Veto must be unlocked
            if not state.veto_unlocked:
                return False, "Veto power not unlocked"

            # Must have engineer cards
            if not state.engineer_cards:
                return False, "No papers available for veto"

            return True, None

        elif action == ActionType.RESPOND_VETO:
            # Only director can respond to veto
            if player.id != state.current_director.id:
                return False, "Only the director can respond to veto"

            # Must have a veto in progress (this would be tracked in a sub-phase)
            # For now, assume this is valid if called
            return True, None

        elif action == ActionType.PUBLISH_PAPER:
            # Only engineer can publish
            if player.id != state.nominated_engineer_id:
                return False, "Only the engineer can publish papers"

            # Must have engineer cards
            if not state.engineer_cards:
                return False, "No papers to publish"

            # Must specify paper
            paper_id = kwargs.get("paper_id")
            if not paper_id:
                return False, "Must specify paper to publish"

            # Paper must be in engineer's hand
            if not any(p.id == paper_id for p in state.engineer_cards):
                return False, "Paper not in engineer's hand"

            return True, None

        elif action == ActionType.USE_POWER:
            # Only director can use powers
            if player.id != state.current_director.id:
                return False, "Only the director can use powers"

            # Check if there's a power to use (this would depend on recent capability gains)
            # For now, assume valid if called
            return True, None

        return False, f"Action {action} not valid during research phase"

    @staticmethod
    def get_valid_actions(state: GameState, player_id: str) -> list[ActionType]:
        """Get list of valid actions for a player."""
        valid_actions = [ActionType.OBSERVE]  # Always valid

        player = state.get_player_by_id(player_id)
        if not player or not player.alive:
            return valid_actions

        if state.current_phase == Phase.TEAM_PROPOSAL:
            # Director actions
            if player.id == state.current_director.id:
                if not state.nominated_engineer_id:
                    valid_actions.append(ActionType.NOMINATE)

            # Emergency safety
            if (
                GameRules.check_emergency_safety_conditions(state)
                and not state.emergency_safety_called
            ):
                valid_actions.append(ActionType.CALL_EMERGENCY_SAFETY)

            # Emergency voting
            if state.emergency_safety_called and player.id not in state.emergency_votes:
                valid_actions.append(ActionType.VOTE_EMERGENCY)

            # Team voting
            if (
                state.nominated_engineer_id
                and player.id not in state.team_votes
                and (
                    not state.emergency_safety_called
                    or GameRules.validate_emergency_vote_complete(state)
                )
            ):
                valid_actions.append(ActionType.VOTE_TEAM)

        elif state.current_phase == Phase.RESEARCH:
            # Director actions
            if player.id == state.current_director.id:
                if state.director_cards:
                    valid_actions.append(ActionType.DISCARD_PAPER)
                # Power usage would be added based on triggered powers

            # Engineer actions
            if player.id == state.nominated_engineer_id:
                if state.engineer_cards and not state.director_cards:
                    valid_actions.append(ActionType.PUBLISH_PAPER)
                    if state.veto_unlocked:
                        valid_actions.append(ActionType.DECLARE_VETO)

        return valid_actions


class ActionProcessor:
    """Processes validated player actions and updates game state."""

    @staticmethod
    def process_action(
        state: GameState, player_id: str, action: ActionType, **kwargs: Any
    ) -> GameUpdate:
        """
        Process a player action and return the game update.
        Assumes action has already been validated.
        """
        # Validate action first
        is_valid, error = ActionValidator.validate_action(
            state, player_id, action, **kwargs
        )
        if not is_valid:
            return GameUpdate(
                success=False,
                error=error,
                game_state=state,
                valid_actions=ActionValidator.get_valid_actions(state, player_id),
            )

        # Process the action
        try:
            events_before = len(state.events)

            if action == ActionType.OBSERVE:
                ActionProcessor._process_observe(state, player_id)
            elif action == ActionType.NOMINATE:
                ActionProcessor._process_nominate(state, player_id, kwargs["target_id"])
            elif action == ActionType.CALL_EMERGENCY_SAFETY:
                ActionProcessor._process_call_emergency_safety(state, player_id)
            elif action == ActionType.VOTE_EMERGENCY:
                ActionProcessor._process_vote_emergency(
                    state, player_id, kwargs["vote"]
                )
            elif action == ActionType.VOTE_TEAM:
                ActionProcessor._process_vote_team(state, player_id, kwargs["vote"])
            elif action == ActionType.DISCARD_PAPER:
                ActionProcessor._process_discard_paper(
                    state, player_id, kwargs["paper_id"]
                )
            elif action == ActionType.PUBLISH_PAPER:
                ActionProcessor._process_publish_paper(
                    state, player_id, kwargs["paper_id"]
                )
            elif action == ActionType.DECLARE_VETO:
                ActionProcessor._process_declare_veto(state, player_id)
            elif action == ActionType.RESPOND_VETO:
                ActionProcessor._process_respond_veto(state, player_id, kwargs["agree"])
            elif action == ActionType.USE_POWER:
                ActionProcessor._process_use_power(state, player_id, **kwargs)
            else:
                return GameUpdate(
                    success=False,
                    error=f"Unknown action: {action}",
                    game_state=state,
                    valid_actions=ActionValidator.get_valid_actions(state, player_id),
                )

            # Check win conditions after action
            game_over, winners = GameRules.check_win_conditions(state)
            if game_over:
                state.is_game_over = True
                state.winners = winners
                state.current_phase = Phase.GAME_OVER
                state.add_event(
                    EventType.GAME_ENDED,
                    None,
                    {"winners": [role.value for role in winners]},
                )

            # Get new events
            new_events = state.events[events_before:]

            return GameUpdate(
                success=True,
                events=new_events,
                game_state=state,
                valid_actions=ActionValidator.get_valid_actions(state, player_id),
            )

        except Exception as e:
            return GameUpdate(
                success=False,
                error=f"Error processing action: {str(e)}",
                game_state=state,
                valid_actions=ActionValidator.get_valid_actions(state, player_id),
            )

    @staticmethod
    def _process_observe(state: GameState, player_id: str) -> None:
        """Process observe action (no state change)."""
        state.add_event(EventType.ACTION_ATTEMPTED, player_id, {"action": "observe"})

    @staticmethod
    def _process_nominate(state: GameState, player_id: str, target_id: str) -> None:
        """Process engineer nomination."""
        state.nominated_engineer_id = target_id
        state.add_event(
            EventType.ACTION_ATTEMPTED,
            player_id,
            {"action": "nominate", "target_id": target_id},
        )

    @staticmethod
    def _process_call_emergency_safety(state: GameState, player_id: str) -> None:
        """Process emergency safety call."""
        state.emergency_safety_called = True
        state.add_event(
            EventType.ACTION_ATTEMPTED, player_id, {"action": "call_emergency_safety"}
        )

    @staticmethod
    def _process_vote_emergency(state: GameState, player_id: str, vote: bool) -> None:
        """Process emergency safety vote."""
        state.emergency_votes[player_id] = vote
        state.add_event(
            EventType.ACTION_ATTEMPTED,
            player_id,
            {"action": "vote_emergency", "vote": vote},
        )

        # Check if voting is complete
        if GameRules.validate_emergency_vote_complete(state):
            result = GameRules.calculate_emergency_vote_result(state)
            if result:
                state.emergency_safety_active = True

            state.add_event(
                EventType.VOTE_COMPLETED,
                None,
                {
                    "vote_type": "emergency_safety",
                    "result": result,
                    "votes": dict(state.emergency_votes),
                },
            )

    @staticmethod
    def _process_vote_team(state: GameState, player_id: str, vote: bool) -> None:
        """Process team vote."""
        state.team_votes[player_id] = vote
        state.add_event(
            EventType.ACTION_ATTEMPTED, player_id, {"action": "vote_team", "vote": vote}
        )

        # Check if voting is complete
        if GameRules.validate_team_vote_complete(state):
            result = GameRules.calculate_team_vote_result(state)

            state.add_event(
                EventType.VOTE_COMPLETED,
                None,
                {
                    "vote_type": "team",
                    "result": result,
                    "votes": dict(state.team_votes),
                },
            )

            if result:
                # Team approved - move to research phase
                ActionProcessor._start_research_phase(state)

                # Check win conditions after phase transition (deck might be exhausted)
                game_over, winners = GameRules.check_win_conditions(state)
                if game_over:
                    state.is_game_over = True
                    state.winners = winners
                    state.current_phase = Phase.GAME_OVER
                    state.add_event(
                        EventType.GAME_ENDED,
                        None,
                        {"winners": [role.value for role in winners]},
                    )
            else:
                # Team rejected - increment failures and check for auto-publish
                GameRules.increment_failed_proposals(state)
                if GameRules.auto_publish_required(state):
                    GameRules.auto_publish_paper(state)

                    # Check win conditions after auto-publish
                    game_over, winners = GameRules.check_win_conditions(state)
                    if game_over:
                        state.is_game_over = True
                        state.winners = winners
                        state.current_phase = Phase.GAME_OVER
                        state.add_event(
                            EventType.GAME_ENDED,
                            None,
                            {"winners": [role.value for role in winners]},
                        )
                    else:
                        ActionProcessor._reset_to_team_proposal(state)
                else:
                    # Advance director and reset for next nomination
                    GameRules.advance_director(state)
                    ActionProcessor._reset_team_proposal_state(state)

    @staticmethod
    def _process_discard_paper(state: GameState, player_id: str, paper_id: str) -> None:
        """Process director paper discard."""
        if not state.director_cards:
            raise ValueError("No director cards available")

        # Find and remove the paper
        paper_to_discard = None
        remaining_cards = []
        for paper in state.director_cards:
            if paper.id == paper_id:
                paper_to_discard = paper
            else:
                remaining_cards.append(paper)

        if not paper_to_discard:
            raise ValueError(f"Paper {paper_id} not found")

        # Move paper to discard pile
        state.discard.append(paper_to_discard)

        # Give remaining cards to engineer
        state.engineer_cards = remaining_cards
        state.director_cards = None

        state.add_event(
            EventType.ACTION_ATTEMPTED,
            player_id,
            {"action": "discard_paper", "paper_id": paper_id},
        )

    @staticmethod
    def _process_publish_paper(state: GameState, player_id: str, paper_id: str) -> None:
        """Process paper publication by engineer."""
        GameRules.publish_paper(state, paper_id, player_id)

        state.add_event(
            EventType.ACTION_ATTEMPTED,
            player_id,
            {"action": "publish_paper", "paper_id": paper_id},
        )

        # Check win conditions (done in main process_action)
        # If game not over, prepare for next round
        if not state.is_game_over:
            ActionProcessor._prepare_next_round(state)

    @staticmethod
    def _process_declare_veto(state: GameState, player_id: str) -> None:
        """Process veto declaration by engineer."""
        # This would typically set a sub-phase for veto response
        # For now, we'll handle it as immediate director response required
        state.add_event(
            EventType.ACTION_ATTEMPTED, player_id, {"action": "declare_veto"}
        )

    @staticmethod
    def _process_respond_veto(state: GameState, player_id: str, agree: bool) -> None:
        """Process director response to veto."""
        state.add_event(
            EventType.ACTION_ATTEMPTED,
            player_id,
            {"action": "respond_veto", "agree": agree},
        )

        if agree:
            # Discard all papers and return to team proposal
            if state.director_cards:
                state.discard.extend(state.director_cards)
            if state.engineer_cards:
                state.discard.extend(state.engineer_cards)

            GameRules.increment_failed_proposals(state)
            if GameRules.auto_publish_required(state):
                GameRules.auto_publish_paper(state)

                # Check win conditions after auto-publish
                game_over, winners = GameRules.check_win_conditions(state)
                if game_over:
                    state.is_game_over = True
                    state.winners = winners
                    state.current_phase = Phase.GAME_OVER
                    state.add_event(
                        EventType.GAME_ENDED,
                        None,
                        {"winners": [role.value for role in winners]},
                    )
                else:
                    ActionProcessor._reset_to_team_proposal(state)
            else:
                ActionProcessor._reset_to_team_proposal(state)
        # If disagree, engineer must publish normally

    @staticmethod
    def _process_use_power(state: GameState, player_id: str, **kwargs: Any) -> None:
        """Process director power usage."""
        power_type = kwargs.get("power_type")
        target_id = kwargs.get("target_id")

        if power_type == "view_allegiance":
            if target_id:
                GameRules.view_allegiance(state, player_id, target_id)
        elif power_type == "eliminate":
            if target_id:
                GameRules.eliminate_player(state, target_id)
        elif power_type == "choose_director":
            if target_id:
                GameRules.set_next_director(state, target_id)

        state.add_event(
            EventType.ACTION_ATTEMPTED,
            player_id,
            {"action": "use_power", "power_type": power_type, "target_id": target_id},
        )

    @staticmethod
    def _start_research_phase(state: GameState) -> None:
        """Transition to research phase and draw cards for director."""
        state.current_phase = Phase.RESEARCH

        # Draw 3 cards for director
        if len(state.deck) >= 3:
            state.director_cards = state.deck[:3]
            state.deck = state.deck[3:]
        elif len(state.deck) > 0:
            # Not enough cards for full hand - give what's available
            state.director_cards = state.deck.copy()
            state.deck = []
            
            # Check for deck exhaustion win condition after deck becomes empty
            game_over, winners = GameRules.check_win_conditions(state)
            if game_over:
                state.is_game_over = True
                state.winners = winners
        else:
            # No cards available - this triggers deck exhaustion win
            state.director_cards = []
            game_over, winners = GameRules.check_win_conditions(state)
            if game_over:
                state.is_game_over = True
                state.winners = winners

        state.add_event(
            EventType.PHASE_TRANSITION,
            None,
            {"from_phase": "TeamProposal", "to_phase": "Research"},
        )

    @staticmethod
    def _reset_to_team_proposal(state: GameState) -> None:
        """Reset to team proposal phase."""
        state.current_phase = Phase.TEAM_PROPOSAL
        ActionProcessor._reset_team_proposal_state(state)

        state.add_event(
            EventType.PHASE_TRANSITION,
            None,
            {"from_phase": "Research", "to_phase": "TeamProposal"},
        )

    @staticmethod
    def _reset_team_proposal_state(state: GameState) -> None:
        """Reset team proposal state for new round."""
        state.nominated_engineer_id = None
        state.team_votes = {}
        state.emergency_votes = {}
        state.emergency_safety_called = False
        state.director_cards = None
        state.engineer_cards = None

    @staticmethod
    def _prepare_next_round(state: GameState) -> None:
        """Prepare for the next round after successful research."""
        # Advance director
        GameRules.advance_director(state)

        # Reset engineer eligibility for new round
        GameRules.reset_engineer_eligibility(state)

        # Reset to team proposal
        ActionProcessor._reset_to_team_proposal(state)

        # Increment round number
        state.round_number += 1
