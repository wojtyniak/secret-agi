"""Async GameEngine with database persistence for Secret AGI."""

import random
import uuid
from typing import Any

from ..database.connection import get_async_session, init_database
from ..database.operations import GameOperations, RecoveryOperations
from ..settings import get_database_url
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
    Async game engine for Secret AGI with optional database persistence.
    Manages game lifecycle, state, and player actions with full persistence.
    """

    def __init__(self, database_url: str | None = None) -> None:
        """
        Initialize GameEngine with optional database URL override.

        Args:
            database_url: Optional database URL. If not provided, uses centralized configuration.
        """
        self.state_manager = GameStateManager()
        self._current_state: GameState | None = None
        self._game_id: str | None = None
        self._database_url = database_url

    async def init_database(self, database_url: str | None = None) -> None:
        """Initialize the database connection using centralized configuration."""
        # Use provided URL, instance URL, or centralized configuration
        url = database_url or self._database_url
        if url is None:
            url = get_database_url()
        else:
            # Apply the same URL conversion logic as centralized configuration
            if url.startswith("sqlite://"):
                url = url.replace("sqlite://", "sqlite+aiosqlite://")
        await init_database(url)

    async def create_game(self, config: GameConfig) -> str:
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

        # Save to database
        async with get_async_session() as session:
            # Create game record with the generated game_id
            db_game_id = await GameOperations.create_game(session, config)
            # Use the generated game_id for consistency
            game_id = db_game_id
            state.game_id = game_id

            # Save initial state
            await GameOperations.save_game_state(session, game_id, 0, state)

        # Save in memory
        self._current_state = state
        self._game_id = game_id
        self.state_manager.save_state_snapshot(state)

        return game_id

    async def load_game(self, game_id: str, turn: int | None = None) -> bool:
        """
        Load a game from the database.
        Returns True if successful, False if game not found.
        """
        async with get_async_session() as session:
            # Check if game exists and get state data
            state_data = await GameOperations.load_game_state(session, game_id, turn)

            if state_data:
                try:
                    # Reconstruct GameState from JSON data
                    # Note: This is a simplified implementation that works because
                    # the current GameState structure doesn't have complex nested objects
                    # that require special deserialization
                    reconstructed_state = self._reconstruct_game_state(
                        state_data, game_id
                    )

                    # Set as current state
                    self._current_state = reconstructed_state
                    self._game_id = game_id
                    self.state_manager.save_state_snapshot(reconstructed_state)

                    return True
                except Exception:
                    # If reconstruction fails, game can't be loaded
                    return False

            return False

    def _reconstruct_game_state(
        self, state_data: dict[str, Any], game_id: str
    ) -> GameState:
        """
        Reconstruct a GameState from JSON data.

        This handles the conversion of string enum values back to proper enum types.
        """
        # Create a new GameState with the game_id
        state = GameState(game_id=game_id)

        # Copy basic fields that don't need enum conversion
        for field in [
            "turn_number",
            "round_number",
            "capability",
            "safety",
            "failed_proposals",
            "is_game_over",
            "current_director_index",
        ]:
            if field in state_data:
                setattr(state, field, state_data[field])

        # Handle enum fields
        if "current_phase" in state_data:
            state.current_phase = Phase(state_data["current_phase"])

        # Handle complex list fields
        if "players" in state_data:
            state.players = [self._reconstruct_player(p) for p in state_data["players"]]

        if "deck" in state_data:
            from .models import Paper

            state.deck = [Paper(**paper) for paper in state_data["deck"]]

        if "discard" in state_data:
            from .models import Paper

            state.discard = [Paper(**paper) for paper in state_data["discard"]]

        if "winners" in state_data:
            state.winners = [Role(role) for role in state_data["winners"]]

        # Handle optional card states
        if "director_cards" in state_data and state_data["director_cards"]:
            from .models import Paper

            state.director_cards = [
                Paper(**paper) for paper in state_data["director_cards"]
            ]

        if "engineer_cards" in state_data and state_data["engineer_cards"]:
            from .models import Paper

            state.engineer_cards = [
                Paper(**paper) for paper in state_data["engineer_cards"]
            ]

        # Handle optional fields
        for field in [
            "nominated_engineer",
            "emergency_safety_active",
            "veto_unlocked",
            "agi_must_reveal",
            "veto_declared",
        ]:
            if field in state_data:
                setattr(state, field, state_data[field])

        # Handle vote dictionaries
        if "team_votes" in state_data and state_data["team_votes"]:
            state.team_votes = state_data["team_votes"]

        if "emergency_votes" in state_data and state_data["emergency_votes"]:
            state.emergency_votes = state_data["emergency_votes"]

        # Handle viewed allegiances
        if "viewed_allegiances" in state_data and state_data["viewed_allegiances"]:
            state.viewed_allegiances = {
                viewer_id: {
                    target_id: Allegiance(allegiance)
                    for target_id, allegiance in targets.items()
                }
                for viewer_id, targets in state_data["viewed_allegiances"].items()
            }

        return state

    def _reconstruct_player(self, player_data: dict[str, Any]) -> Player:
        """Reconstruct a Player from JSON data."""
        return Player(
            id=player_data["id"],
            role=Role(player_data["role"]),
            allegiance=Allegiance(player_data["allegiance"]),
            alive=player_data["alive"],
            was_last_engineer=player_data["was_last_engineer"],
        )

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
                allegiance=Allegiance.ACCELERATION
                if roles[i] in [Role.ACCELERATIONIST, Role.AGI]
                else Allegiance.SAFETY,
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

    async def perform_action(
        self, player_id: str, action: ActionType, **kwargs: Any
    ) -> GameUpdate:
        """
        Perform a player action and return the result.
        """
        if not self._current_state or not self._game_id:
            return GameUpdate(success=False, error="No active game")

        # Increment turn number
        self._current_state.turn_number += 1
        turn_number = self._current_state.turn_number

        # Process the action
        result = ActionProcessor.process_action(
            self._current_state, player_id, action, **kwargs
        )

        # Save to database
        if self._game_id:
            async with get_async_session() as session:
                # Record action attempt
                action_id = await GameOperations.record_action(
                    session, self._game_id, turn_number, player_id, action, kwargs
                )

                # Complete action record
                await GameOperations.complete_action(
                    session, action_id, result.success, result.error
                )

                # Save state snapshot after successful action
                if result.success:
                    await GameOperations.save_game_state(
                        session, self._game_id, turn_number, self._current_state
                    )

        # Always save in-memory state
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

    async def save_game(self) -> str:
        """
        Save the current game state and return a save ID.
        """
        if not self._current_state or not self._game_id:
            raise ValueError("No active game to save")

        async with get_async_session() as session:
            state_id = await GameOperations.save_game_state(
                session,
                self._game_id,
                self._current_state.turn_number,
                self._current_state,
            )
            return state_id

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

    async def simulate_to_completion(self, max_turns: int = 1000) -> dict[str, Any]:
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

                    result = await self.perform_action(player.id, action, **kwargs)

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

    # Recovery and Management Methods

    async def recover_interrupted_game(self, game_id: str) -> dict[str, Any]:
        """
        Recover a game that was interrupted during execution.

        Returns a dictionary with recovery information:
        - success: bool indicating if recovery was successful
        - recovery_type: type of recovery performed
        - last_valid_turn: the turn number we recovered to
        - incomplete_actions: number of incomplete actions cleaned up
        - error: error message if recovery failed
        """
        try:
            async with get_async_session() as session:
                # Analyze the failure type
                failure_analysis = await RecoveryOperations.analyze_failure_type(
                    session, game_id
                )

                # Mark incomplete actions as failed
                incomplete_count = (
                    await RecoveryOperations.mark_incomplete_actions_failed(
                        session, game_id, "Recovered from interruption"
                    )
                )

                # Get the last consistent state
                last_state_info = await RecoveryOperations.get_last_consistent_state(
                    session, game_id
                )

                if last_state_info:
                    turn_number, state_data = last_state_info

                    # Reconstruct the state from JSON data
                    state = self._reconstruct_game_state(state_data, game_id)

                    # Load the recovered state
                    self._current_state = state
                    self._game_id = game_id
                    self.state_manager.save_state_snapshot(state)

                    return {
                        "success": True,
                        "recovery_type": failure_analysis["type"].value,
                        "last_valid_turn": turn_number,
                        "incomplete_actions": incomplete_count,
                        "error": None,
                    }
                else:
                    return {
                        "success": False,
                        "recovery_type": failure_analysis["type"].value,
                        "last_valid_turn": 0,
                        "incomplete_actions": incomplete_count,
                        "error": "No consistent state found to recover to",
                    }

        except Exception as e:
            return {
                "success": False,
                "recovery_type": "unknown",
                "last_valid_turn": 0,
                "incomplete_actions": 0,
                "error": f"Recovery failed: {str(e)}",
            }

    @staticmethod
    async def find_interrupted_games() -> list[str]:
        """
        Find all games that were interrupted and need recovery.

        Returns a list of game IDs that have incomplete actions.
        """
        async with get_async_session() as session:
            return await RecoveryOperations.find_interrupted_games(session)

    @staticmethod
    async def analyze_game_failure(game_id: str) -> dict[str, Any]:
        """
        Analyze the type of failure for a specific game.

        Returns detailed information about what went wrong and how to recover.
        """
        async with get_async_session() as session:
            return await RecoveryOperations.analyze_failure_type(session, game_id)

    async def restart_from_turn(self, game_id: str, turn_number: int) -> bool:
        """
        Restart a game from a specific turn number.

        This loads the game state from that turn and allows continuation.
        Returns True if successful, False if the turn doesn't exist.
        """
        return await self.load_game(game_id, turn_number)

    async def create_checkpoint(self) -> str:
        """
        Create a checkpoint of the current game state.

        Returns the checkpoint ID (state_id) for later recovery.
        """
        if not self._current_state or not self._game_id:
            raise ValueError("No active game to checkpoint")

        return await self.save_game()

    async def restore_from_checkpoint(self, game_id: str, checkpoint_id: str) -> bool:
        """
        Restore a game from a specific checkpoint (state_id).

        Note: This is a placeholder for future implementation where we can
        load by state_id instead of just turn number.
        """
        # For now, we don't have state_id based loading implemented
        # This would require extending the database operations
        return False


# Convenience functions for common operations
async def create_game(
    player_ids: list[str], seed: int | None = None, database_url: str | None = None
) -> GameEngine:
    """
    Convenience function to create a new async game with centralized configuration.

    Args:
        player_ids: List of player identifiers
        seed: Optional random seed for reproducible games
        database_url: Optional database URL override (uses centralized config if None)
    """
    config = GameConfig(player_count=len(player_ids), player_ids=player_ids, seed=seed)

    # Always use centralized configuration system to ensure proper URL handling
    engine = GameEngine(database_url=database_url)
    await engine.init_database()
    await engine.create_game(config)
    return engine


async def run_random_game(
    player_count: int = 5, seed: int | None = None, database_url: str | None = None
) -> dict[str, Any]:
    """
    Convenience function to run a complete random async game with centralized configuration.

    Args:
        player_count: Number of players (5-10)
        seed: Optional random seed for reproducible games
        database_url: Optional database URL override (uses centralized config if None)
    """
    player_ids = [f"player_{i}" for i in range(player_count)]
    engine = await create_game(player_ids, seed, database_url)
    return await engine.simulate_to_completion()


async def recover_game(game_id: str, database_url: str | None = None) -> GameEngine:
    """
    Convenience function to recover an interrupted game.

    Args:
        game_id: The ID of the game to recover
        database_url: Optional database URL override (uses centralized config if None)

    Returns:
        GameEngine instance with the recovered game loaded

    Raises:
        ValueError: If recovery fails
    """
    engine = GameEngine(database_url=database_url)
    await engine.init_database()

    recovery_result = await engine.recover_interrupted_game(game_id)

    if not recovery_result["success"]:
        raise ValueError(f"Game recovery failed: {recovery_result['error']}")

    return engine


async def load_game(
    game_id: str, turn: int | None = None, database_url: str | None = None
) -> GameEngine:
    """
    Convenience function to load a game from the database.

    Args:
        game_id: The ID of the game to load
        turn: Optional specific turn to load (loads latest if None)
        database_url: Optional database URL override (uses centralized config if None)

    Returns:
        GameEngine instance with the loaded game

    Raises:
        ValueError: If loading fails
    """
    engine = GameEngine(database_url=database_url)
    await engine.init_database()

    success = await engine.load_game(game_id, turn)

    if not success:
        raise ValueError(
            f"Failed to load game {game_id}" + (f" at turn {turn}" if turn else "")
        )

    return engine


async def find_interrupted_games(database_url: str | None = None) -> list[str]:
    """
    Convenience function to find all interrupted games.

    Args:
        database_url: Optional database URL override (uses centralized config if None)

    Returns:
        List of game IDs that need recovery
    """
    # Initialize database if needed
    engine = GameEngine(database_url=database_url)
    await engine.init_database()

    return await GameEngine.find_interrupted_games()
