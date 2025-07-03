"""Main GameEngine class for Secret AGI."""

import random
import uuid
from typing import Any

from .actions import ActionProcessor, ActionValidator
from .events import EventFilter, GameStateManager
from .models import (
    ActionType,
    Allegiance,
    GameConfig,
    GameState,
    GameUpdate,
    Phase,
    Player,
    Role,
    create_standard_deck,
    get_role_distribution,
)
from .rules import GameRules


class GameEngine:
    """
    Main game engine for Secret AGI.
    Manages game lifecycle, state, and player actions.
    """

    def __init__(self) -> None:
        self.state_manager = GameStateManager()
        self._current_state: GameState | None = None

    def create_game(self, config: GameConfig) -> str:
        """
        Create a new game with the given configuration.
        Returns the game ID.
        """
        # Set random seed if provided
        if config.seed is not None:
            random.seed(config.seed)

        # Create game state
        game_id = str(uuid.uuid4())
        state = GameState(game_id=game_id)

        # Create and assign roles
        players = self._create_players(config)
        state.players = players

        # Create and shuffle deck
        deck = create_standard_deck()
        random.shuffle(deck)
        state.deck = deck

        # Set random starting director
        alive_indices = [i for i, p in enumerate(players) if p.alive]
        state.current_director_index = random.choice(alive_indices)

        # Initialize state
        state.current_phase = Phase.TEAM_PROPOSAL

        # Save initial state
        self._current_state = state
        self.state_manager.save_state_snapshot(state)

        return game_id

    def _create_players(self, config: GameConfig) -> list[Player]:
        """Create players with appropriate role assignments."""
        role_distribution = get_role_distribution(config.player_count)

        # Create role list
        roles = []
        for role, count in role_distribution.items():
            roles.extend([role] * count)

        # Shuffle roles
        random.shuffle(roles)

        # Create players
        players = []
        for i, player_id in enumerate(config.player_ids):
            player = Player(
                id=player_id,
                role=roles[i],
                allegiance=Allegiance.ACCELERATION if roles[i] in [Role.ACCELERATIONIST, Role.AGI] else Allegiance.SAFETY,
            )
            players.append(player)

        return players

    def get_game_state(self, player_id: str | None = None) -> GameState | None:
        """
        Get the current game state.
        If player_id is provided, returns filtered view for that player.
        If player_id is None, returns full state (for debugging/testing).
        """
        if not self._current_state:
            return None

        if player_id:
            return EventFilter.filter_game_state_for_player(
                self._current_state, player_id
            )
        else:
            return self.state_manager.get_current_state()

    def get_valid_actions(self, player_id: str) -> list[ActionType]:
        """Get valid actions for a player."""
        if not self._current_state:
            return []

        return ActionValidator.get_valid_actions(self._current_state, player_id)

    def perform_action(
        self, player_id: str, action: ActionType, **kwargs: Any
    ) -> GameUpdate:
        """
        Perform a player action and return the result.
        """
        if not self._current_state:
            return GameUpdate(success=False, error="No active game")

        # Increment turn number
        self._current_state.turn_number += 1

        # Process the action
        result = ActionProcessor.process_action(
            self._current_state, player_id, action, **kwargs
        )

        # Save state snapshot after action
        if result.success:
            self.state_manager.save_state_snapshot(self._current_state)

        # Return filtered state for the acting player (only if action succeeded and player exists)
        if (
            result.game_state
            and result.success
            and self._current_state.get_player_by_id(player_id)
        ):
            result.game_state = EventFilter.filter_game_state_for_player(
                result.game_state, player_id
            )

        return result

    def is_game_over(self) -> bool:
        """Check if the game is over."""
        return self._current_state.is_game_over if self._current_state else False

    def get_winners(self) -> list[Role]:
        """Get the winning roles."""
        return self._current_state.winners if self._current_state else []

    def get_public_info(self) -> dict[str, Any]:
        """Get public information visible to all players."""
        if not self._current_state:
            return {}

        from .events import PublicInformationProvider

        return PublicInformationProvider.get_public_game_info(self._current_state)

    def get_events_for_player(self, player_id: str, since_turn: int = 0) -> list:
        """Get events visible to a player since a specific turn."""
        return self.state_manager.get_events_for_player(player_id, since_turn)

    def save_game(self) -> str:
        """
        Save the current game state and return a save ID.
        For now, this is just the current turn number.
        """
        if not self._current_state:
            raise ValueError("No active game to save")

        return f"{self._current_state.game_id}_{self._current_state.turn_number}"

    def load_game(self, save_id: str) -> bool:
        """
        Load a game from a save ID.
        For now, this is not implemented as we don't have persistence.
        """
        # In a full implementation, this would load from database
        raise NotImplementedError("Game loading not implemented")

    def get_game_stats(self) -> dict[str, Any]:
        """Get game statistics."""
        if not self._current_state:
            return {}

        stats = {
            "game_id": self._current_state.game_id,
            "turn_number": self._current_state.turn_number,
            "round_number": self._current_state.round_number,
            "player_count": len(self._current_state.players),
            "alive_player_count": self._current_state.alive_player_count,
            "capability": self._current_state.capability,
            "safety": self._current_state.safety,
            "deck_size": len(self._current_state.deck),
            "discard_size": len(self._current_state.discard),
            "failed_proposals": self._current_state.failed_proposals,
            "current_phase": self._current_state.current_phase.value,
            "is_game_over": self._current_state.is_game_over,
            "winners": [role.value for role in self._current_state.winners],
        }

        return stats

    def debug_get_full_state(self) -> GameState | None:
        """
        Get the full, unfiltered game state for debugging.
        Should not be used by players during actual gameplay.
        """
        return self.state_manager.get_current_state()

    def simulate_to_completion(self, max_turns: int = 1000) -> dict[str, Any]:
        """
        Simulate the game to completion using random actions.
        Useful for testing game completeness.
        Returns final game statistics.
        """
        if not self._current_state:
            raise ValueError("No active game to simulate")

        turn_count = 0

        while not self.is_game_over() and turn_count < max_turns:
            # Get all alive players
            alive_players = [p for p in self._current_state.players if p.alive]
            if not alive_players:
                break

            # Find a player who has valid actions
            action_taken = False
            for player in alive_players:
                valid_actions = self.get_valid_actions(player.id)
                valid_actions = [a for a in valid_actions if a != ActionType.OBSERVE]

                if valid_actions:
                    # Take a random action
                    action = random.choice(valid_actions)

                    # Generate random parameters based on action type
                    kwargs = self._generate_random_action_params(action, player.id)

                    result = self.perform_action(player.id, action, **kwargs)

                    if result.success:
                        action_taken = True
                        break

            if not action_taken:
                # If no actions available, something is wrong
                break

            turn_count += 1

        return {
            "completed": self.is_game_over(),
            "turns_taken": turn_count,
            "winners": [role.value for role in self.get_winners()],
            "final_stats": self.get_game_stats(),
        }

    def _generate_random_action_params(
        self, action: ActionType, player_id: str
    ) -> dict[str, Any]:
        """Generate random parameters for an action."""
        if not self._current_state:
            return {}

        kwargs: dict[str, Any] = {}

        if action == ActionType.NOMINATE:
            eligible = GameRules.get_eligible_engineers(self._current_state)
            if eligible:
                kwargs["target_id"] = random.choice(eligible)

        elif action in [ActionType.VOTE_TEAM, ActionType.VOTE_EMERGENCY]:
            kwargs["vote"] = random.choice([True, False])

        elif action == ActionType.DISCARD_PAPER:
            if self._current_state.director_cards:
                kwargs["paper_id"] = random.choice(
                    self._current_state.director_cards
                ).id

        elif action == ActionType.PUBLISH_PAPER:
            if self._current_state.engineer_cards:
                kwargs["paper_id"] = random.choice(
                    self._current_state.engineer_cards
                ).id

        elif action == ActionType.RESPOND_VETO:
            kwargs["agree"] = random.choice([True, False])

        elif action == ActionType.USE_POWER:
            # This would need more sophisticated logic based on what powers are available
            alive_players = [
                p.id for p in self._current_state.alive_players if p.id != player_id
            ]
            if alive_players:
                kwargs["target_id"] = random.choice(alive_players)
                kwargs["power_type"] = "view_allegiance"  # Default power

        elif action == ActionType.SEND_CHAT_MESSAGE:
            kwargs["text"] = f"Random message from {player_id}"

        return kwargs


# Convenience functions for common operations
def create_game(player_ids: list[str], seed: int | None = None) -> GameEngine:
    """
    Convenience function to create a new game.
    """
    config = GameConfig(player_count=len(player_ids), player_ids=player_ids, seed=seed)

    engine = GameEngine()
    engine.create_game(config)
    return engine


def run_random_game(
    player_count: int = 5, seed: int | None = None
) -> dict[str, Any]:
    """
    Convenience function to run a complete random game.
    """
    player_ids = [f"player_{i}" for i in range(player_count)]
    engine = create_game(player_ids, seed)
    return engine.simulate_to_completion()
