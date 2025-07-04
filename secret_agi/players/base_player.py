"""Base player interface for Secret AGI players."""

from abc import ABC, abstractmethod
from typing import Any

from ..engine.models import ActionType, GameState, GameUpdate, Role


class BasePlayer(ABC):
    """
    Abstract base class for all Secret AGI players.

    This interface defines the methods that all player implementations must provide.
    Players can be AI agents, human players, or any other decision-making entity.
    """

    def __init__(self, player_id: str):
        """
        Initialize the player.

        Args:
            player_id: Unique identifier for this player
        """
        self.player_id = player_id
        self.game_engine = None  # Will be set when player joins a game

    @abstractmethod
    def choose_action(
        self, game_state: GameState, valid_actions: list[ActionType]
    ) -> tuple[ActionType, dict[str, Any]]:
        """
        Choose an action based on the current game state.

        Args:
            game_state: Current game state (filtered for this player)
            valid_actions: List of actions this player can take

        Returns:
            Tuple of (action_type, action_parameters)

        Example:
            return (ActionType.NOMINATE, {"target_id": "player_2"})
            return (ActionType.VOTE_TEAM, {"vote": True})
            return (ActionType.OBSERVE, {})
        """
        pass

    @abstractmethod
    def on_game_start(self, game_state: GameState) -> None:
        """
        Called when the game starts.

        Players can use this to initialize their strategy, learn their role,
        and identify any known allies.

        Args:
            game_state: Initial game state (filtered for this player)
        """
        pass

    @abstractmethod
    def on_game_update(self, game_update: GameUpdate) -> None:
        """
        Called after each action with the game update.

        Players can use this to track game events, update their internal state,
        and react to other players' actions.

        Args:
            game_update: Update containing events and new game state
        """
        pass

    @abstractmethod
    def on_game_end(self, final_state: GameState) -> None:
        """
        Called when the game ends.

        Optional method for cleanup or learning from the final game state.
        Default implementation does nothing.

        Args:
            final_state: Final game state (filtered for this player)
        """
        pass

    def get_internal_state(self) -> dict[str, Any]:
        """
        Get the player's internal state for debugging/analysis.

        Optional method that returns information about the player's
        internal reasoning, memory, or strategy state.

        Returns:
            Dictionary containing internal state information
        """
        return {"player_id": self.player_id, "type": self.__class__.__name__}

    def set_game_engine(self, game_engine: Any) -> None:
        """
        Set the game engine reference.

        This allows the player to make actions directly through the engine.
        Called by the game orchestrator when the player joins a game.

        Args:
            game_engine: GameEngine instance
        """
        self.game_engine = game_engine

    async def perform_action(self, action: ActionType, **kwargs: Any) -> GameUpdate:
        """
        Perform an action through the game engine.

        Convenience method for players to make actions.

        Args:
            action: Action to perform
            **kwargs: Action parameters

        Returns:
            GameUpdate with result of the action
        """
        if not self.game_engine:
            raise ValueError("Player not connected to game engine")

        return await self.game_engine.perform_action(self.player_id, action, **kwargs)

    def get_valid_actions(self) -> list[ActionType]:
        """
        Get valid actions for this player.

        Convenience method for players to check what actions they can take.

        Returns:
            List of valid action types
        """
        if not self.game_engine:
            return []

        return self.game_engine.get_valid_actions(self.player_id)

    def observe_game_state(self) -> GameState:
        """
        Get the current game state filtered for this player.

        Convenience method for players to observe the current game state.

        Returns:
            Current game state (filtered for this player)
        """
        if not self.game_engine:
            raise ValueError("Player not connected to game engine")

        return self.game_engine.get_game_state(self.player_id)


class HumanPlayer(BasePlayer):
    """
    Human player implementation that prompts for input.

    This is a simple implementation for testing and demonstration.
    In a full system, this would be replaced by a web interface.
    """

    def __init__(self, player_id: str):
        super().__init__(player_id)
        self.role: Role | None = None
        self.known_allies: list[str] = []

    def choose_action(
        self, game_state: GameState, valid_actions: list[ActionType]
    ) -> tuple[ActionType, dict[str, Any]]:
        """Prompt human player for action choice."""
        print(f"\n=== {self.player_id}'s Turn ===")
        print(f"Phase: {game_state.current_phase.value}")
        print(f"Capability: {game_state.capability}, Safety: {game_state.safety}")
        print(f"You are: {self.role}")
        print(f"Valid actions: {[a.value for a in valid_actions]}")

        # Simple text-based input (would be replaced by web UI)
        while True:
            action_input = input("Choose action: ").strip().lower()

            for action in valid_actions:
                if action.value.lower() == action_input:
                    params = self._get_action_parameters(action, game_state)
                    return action, params

            print("Invalid action. Try again.")

    def _get_action_parameters(
        self, action: ActionType, game_state: GameState
    ) -> dict[str, Any]:
        """Get parameters for the chosen action."""
        params: dict[str, Any] = {}

        if action == ActionType.NOMINATE:
            eligible = [
                p.id for p in game_state.alive_players if not p.was_last_engineer
            ]
            print(f"Eligible engineers: {eligible}")
            target = input("Nominate player: ").strip()
            params["target_id"] = target

        elif action in [ActionType.VOTE_TEAM, ActionType.VOTE_EMERGENCY]:
            vote = input("Vote (yes/no): ").strip().lower()
            params["vote"] = vote in ["yes", "y", "true", "1"]

        elif action == ActionType.DISCARD_PAPER:
            if game_state.director_cards:
                print("Available papers:")
                for i, paper in enumerate(game_state.director_cards):
                    print(f"  {i}: {paper.id} (C:{paper.capability}, S:{paper.safety})")
                choice = int(input("Choose paper to discard (index): "))
                params["paper_id"] = game_state.director_cards[choice].id

        elif action == ActionType.PUBLISH_PAPER:
            if game_state.engineer_cards:
                print("Available papers:")
                for i, paper in enumerate(game_state.engineer_cards):
                    print(f"  {i}: {paper.id} (C:{paper.capability}, S:{paper.safety})")
                choice = int(input("Choose paper to publish (index): "))
                params["paper_id"] = game_state.engineer_cards[choice].id

        elif action == ActionType.RESPOND_VETO:
            agree = input("Agree to veto (yes/no): ").strip().lower()
            params["agree"] = agree in ["yes", "y", "true", "1"]

        return params

    def on_game_start(self, game_state: GameState) -> None:
        """Learn role and allies at game start."""
        # Find this player in the game state
        for player in game_state.players:
            if player.id == self.player_id:
                self.role = player.role
                break

        # Find known allies (Accelerationists and AGI know each other)
        if self.role in [Role.ACCELERATIONIST, Role.AGI]:
            for player in game_state.players:
                if player.id != self.player_id and player.role in [
                    Role.ACCELERATIONIST,
                    Role.AGI,
                ]:
                    self.known_allies.append(player.id)

        print("\n=== Game Started ===")
        print(f"You are: {self.role}")
        if self.known_allies:
            print(f"Known allies: {self.known_allies}")

    def on_game_update(self, game_update: GameUpdate) -> None:
        """Display game events to human player."""
        if game_update.events:
            print("\n=== Recent Events ===")
            for event in game_update.events:
                print(f"  {event.type.value}: {event.data}")

    def get_internal_state(self) -> dict[str, Any]:
        """Return human player's known information."""
        return {
            **super().get_internal_state(),
            "role": self.role,
            "known_allies": self.known_allies,
        }
