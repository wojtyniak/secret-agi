"""Random player implementation for testing Secret AGI game completeness."""

import random
from typing import Any

from ..engine.models import ActionType, GameState, GameUpdate, Role
from .base_player import BasePlayer


class RandomPlayer(BasePlayer):
    """
    A player that makes random valid moves.

    This implementation is designed for testing game completeness and
    ensuring that games always terminate properly. It makes random
    but valid decisions for all game situations.
    """

    def __init__(self, player_id: str, seed: int | None = None):
        """
        Initialize RandomPlayer.

        Args:
            player_id: Unique identifier for this player
            seed: Optional random seed for reproducible behavior
        """
        super().__init__(player_id)
        if seed is not None:
            random.seed(seed)

        self.role: Role | None = None
        self.known_allies: list[str] = []
        self.action_count = 0
        self.game_history: list[dict[str, Any]] = []

    def choose_action(
        self, game_state: GameState, valid_actions: list[ActionType]
    ) -> tuple[ActionType, dict[str, Any]]:
        """
        Choose a random action from valid actions.

        Prioritizes non-observe actions to keep the game progressing.
        """
        self.action_count += 1

        # Filter out observe actions if other actions are available
        non_observe_actions = [a for a in valid_actions if a != ActionType.OBSERVE]

        action: ActionType
        if non_observe_actions:
            action = random.choice(non_observe_actions)
        else:
            action = ActionType.OBSERVE

        # Generate random parameters for the action
        params = self._generate_action_parameters(action, game_state)

        # Record the decision for analysis
        self.game_history.append(
            {
                "turn": game_state.turn_number,
                "action": action.value,
                "params": params,
                "phase": game_state.current_phase.value,
                "capability": game_state.capability,
                "safety": game_state.safety,
            }
        )

        return action, params

    def _generate_action_parameters(
        self, action: ActionType, game_state: GameState
    ) -> dict[str, Any]:
        """Generate random parameters for the given action."""
        params: dict[str, Any] = {}

        if action == ActionType.NOMINATE:
            # Choose a random eligible engineer
            eligible_engineers = self._get_eligible_engineers(game_state)
            if eligible_engineers:
                params["target_id"] = random.choice(eligible_engineers)

        elif action in [ActionType.VOTE_TEAM, ActionType.VOTE_EMERGENCY]:
            # Random vote with slight bias toward "yes" to keep game moving
            params["vote"] = random.choice([True, True, True, False])  # 75% yes

        elif action == ActionType.DISCARD_PAPER:
            # Randomly discard one of the director's cards
            if game_state.director_cards:
                params["paper_id"] = random.choice(game_state.director_cards).id

        elif action == ActionType.PUBLISH_PAPER:
            # Randomly publish one of the engineer's cards
            if game_state.engineer_cards:
                params["paper_id"] = random.choice(game_state.engineer_cards).id

        elif action == ActionType.DECLARE_VETO:
            # No parameters needed for veto declaration
            pass

        elif action == ActionType.RESPOND_VETO:
            # Random response to veto with slight bias toward disagreeing
            params["agree"] = random.choice([False, False, True])  # 33% agree

        elif action == ActionType.USE_POWER:
            # Generate parameters for power usage
            power_params = self._generate_power_parameters(game_state)
            params.update(power_params)

        elif action == ActionType.SEND_CHAT_MESSAGE:
            # Send a simple random message
            messages = [
                "I think we should be careful",
                "This seems risky",
                "I trust this plan",
                "We need to consider safety",
                "This could work",
                "I'm not sure about this",
            ]
            params["text"] = random.choice(messages)

        return params

    def _get_eligible_engineers(self, game_state: GameState) -> list[str]:
        """Get list of players eligible to be engineers."""
        return [p.id for p in game_state.alive_players if not p.was_last_engineer]

    def _generate_power_parameters(self, game_state: GameState) -> dict[str, Any]:
        """Generate parameters for power usage."""
        params = {}

        # Get other alive players as potential targets
        other_players = [
            p.id for p in game_state.alive_players if p.id != self.player_id
        ]

        if other_players:
            params["target_id"] = random.choice(other_players)

            # Randomly choose power type (in practice this would be determined by game state)
            power_types = ["view_allegiance", "eliminate", "choose_director"]
            params["power_type"] = random.choice(power_types)

        return params

    def on_game_start(self, game_state: GameState) -> None:
        """Initialize player state at game start."""
        # Find this player's role
        for player in game_state.players:
            if player.id == self.player_id:
                self.role = player.role
                break

        # Identify known allies (Accelerationists and AGI know each other)
        if self.role in [Role.ACCELERATIONIST, Role.AGI]:
            for player in game_state.players:
                if player.id != self.player_id and player.role in [
                    Role.ACCELERATIONIST,
                    Role.AGI,
                ]:
                    self.known_allies.append(player.id)

        # Record game start
        self.game_history.append(
            {
                "event": "game_start",
                "role": self.role.value if self.role else None,
                "known_allies": self.known_allies.copy(),
                "player_count": len(game_state.players),
            }
        )

    def on_game_update(self, game_update: GameUpdate) -> None:
        """Process game updates (no special logic for random player)."""
        # Record significant events for later analysis
        if game_update.events:
            for event in game_update.events:
                if event.type.value in [
                    "game_ended",
                    "paper_published",
                    "phase_transition",
                ]:
                    self.game_history.append(
                        {
                            "event": "update",
                            "event_type": event.type.value,
                            "event_data": event.data,
                        }
                    )

    def on_game_end(self, final_state: GameState) -> None:
        """Record game end state."""
        self.game_history.append(
            {
                "event": "game_end",
                "winners": [role.value for role in final_state.winners],
                "final_capability": final_state.capability,
                "final_safety": final_state.safety,
                "total_turns": final_state.turn_number,
                "actions_taken": self.action_count,
            }
        )

    def get_internal_state(self) -> dict[str, Any]:
        """Return player's internal state for analysis."""
        return {
            **super().get_internal_state(),
            "role": self.role.value if self.role else None,
            "known_allies": self.known_allies.copy(),
            "action_count": self.action_count,
            "game_history_length": len(self.game_history),
            "recent_actions": self.game_history[-5:] if self.game_history else [],
        }

    def get_decision_summary(self) -> dict[str, Any]:
        """Get a summary of this player's decisions during the game."""
        if not self.game_history:
            return {}

        # Count action types
        action_counts: dict[str, int] = {}
        vote_counts = {"yes": 0, "no": 0}

        for entry in self.game_history:
            if entry.get("action"):
                action = entry["action"]
                action_counts[action] = action_counts.get(action, 0) + 1

                # Track voting patterns
                if action in ["vote_team", "vote_emergency"]:
                    vote = entry.get("params", {}).get("vote", False)
                    vote_counts["yes" if vote else "no"] += 1

        return {
            "player_id": self.player_id,
            "role": self.role.value if self.role else None,
            "total_actions": self.action_count,
            "action_breakdown": action_counts,
            "voting_pattern": vote_counts,
            "game_length": len([e for e in self.game_history if e.get("action")]),
        }


class BiasedRandomPlayer(RandomPlayer):
    """
    A random player with biases based on their role.

    Still makes random decisions but with weights that reflect
    what each role might prefer to do.
    """

    def __init__(self, player_id: str, seed: int | None = None):
        super().__init__(player_id, seed)
        self.role_bias: dict[str, Any] = {}

    def on_game_start(self, game_state: GameState) -> None:
        """Set up role-based biases."""
        super().on_game_start(game_state)

        if self.role == Role.SAFETY:
            # Safety researchers prefer to vote yes on teams with allies
            # and vote for emergency safety when capability is high
            self.role_bias = {
                "emergency_safety_threshold": 3,  # Call emergency if cap-safety >= 3
                "team_vote_yes_bias": 0.7,  # Slightly prefer yes votes
                "prefer_safety_papers": True,
            }

        elif self.role == Role.ACCELERATIONIST:
            # Accelerationists prefer capability advancement
            self.role_bias = {
                "emergency_safety_threshold": 6,  # Only call emergency at extreme diff
                "team_vote_yes_bias": 0.8,  # Prefer yes votes to advance game
                "prefer_capability_papers": True,
            }

        elif self.role == Role.AGI:
            # AGI tries to balance advancing capability while staying hidden
            self.role_bias = {
                "emergency_safety_threshold": 5,  # Moderate emergency calling
                "team_vote_yes_bias": 0.75,  # Generally cooperative
                "hide_until_capability": 8,  # Try to stay hidden until C>=8
            }

    def choose_action(
        self, game_state: GameState, valid_actions: list[ActionType]
    ) -> tuple[ActionType, dict[str, Any]]:
        """Make biased random choices based on role."""
        # For emergency safety, use role bias
        if ActionType.CALL_EMERGENCY_SAFETY in valid_actions:
            cap_safety_diff = game_state.capability - game_state.safety
            threshold = self.role_bias.get("emergency_safety_threshold", 4)

            if cap_safety_diff >= threshold:
                return ActionType.CALL_EMERGENCY_SAFETY, {}

        # For voting, use role bias
        if (
            ActionType.VOTE_TEAM in valid_actions
            or ActionType.VOTE_EMERGENCY in valid_actions
        ):
            # Use biased voting but still random
            action_choice = random.choice(
                [a for a in valid_actions if a != ActionType.OBSERVE] or valid_actions
            )
            params = self._generate_biased_vote_parameters(action_choice, game_state)
            return action_choice, params

        # For paper selection, consider role preferences
        if ActionType.PUBLISH_PAPER in valid_actions and game_state.engineer_cards:
            return self._choose_biased_paper(game_state)

        # Default to random choice for other actions
        return super().choose_action(game_state, valid_actions)

    def _generate_biased_vote_parameters(
        self, action: ActionType, game_state: GameState
    ) -> dict[str, Any]:
        """Generate vote parameters with role bias."""
        if action in [ActionType.VOTE_TEAM, ActionType.VOTE_EMERGENCY]:
            yes_bias = self.role_bias.get("team_vote_yes_bias", 0.5)
            vote = random.random() < yes_bias
            return {"vote": vote}

        return self._generate_action_parameters(action, game_state)

    def _choose_biased_paper(
        self, game_state: GameState
    ) -> tuple[ActionType, dict[str, Any]]:
        """Choose paper to publish based on role bias."""
        if not game_state.engineer_cards:
            return ActionType.OBSERVE, {}

        papers = game_state.engineer_cards

        if self.role == Role.SAFETY and self.role_bias.get("prefer_safety_papers"):
            # Prefer papers with higher safety relative to capability
            best_paper = max(papers, key=lambda p: p.safety - p.capability)
        elif self.role in [Role.ACCELERATIONIST, Role.AGI] and self.role_bias.get(
            "prefer_capability_papers"
        ):
            # Prefer papers with higher capability
            best_paper = max(papers, key=lambda p: p.capability)
        else:
            # Random choice
            best_paper = random.choice(papers)

        return ActionType.PUBLISH_PAPER, {"paper_id": best_paper.id}
