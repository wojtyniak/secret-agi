"""Simple orchestrator for managing games with mixed player types."""

import asyncio
import logging
from typing import Any

from ..engine.game_engine import GameEngine
from ..engine.models import ActionType, GameConfig, GameState, GameUpdate
from ..players.base_player import BasePlayer

logger = logging.getLogger(__name__)


class SimpleOrchestrator:
    """
    Simple orchestrator for managing multi-player games with different agent types.
    
    This provides a minimal interface for running games with mixed player types
    (RandomPlayer, LLM agents, HumanPlayer, etc.) without complex coordination.
    """

    def __init__(self, database_url: str | None = None, debug_mode: bool = False):
        """
        Initialize the simple orchestrator.

        Args:
            database_url: Optional database URL override
            debug_mode: Enable debug logging for agent decisions
        """
        self._database_url = database_url
        self._debug_mode = debug_mode
        self._engine: GameEngine | None = None
        self._players: list[BasePlayer] = []
        self._game_id: str | None = None

    async def run_game(
        self, 
        players: list[BasePlayer], 
        config: GameConfig | None = None
    ) -> dict[str, Any]:
        """
        Run a complete game with the given players.

        Args:
            players: List of player instances (any mix of agent types)
            config: Optional game configuration

        Returns:
            Game result dictionary with outcome and statistics

        Raises:
            ValueError: If invalid player count or player configuration
        """
        if not (5 <= len(players) <= 10):
            raise ValueError(f"Invalid player count: {len(players)}. Must be 5-10 players.")

        if len(set(p.player_id for p in players)) != len(players):
            raise ValueError("All players must have unique player_ids")

        self._players = players

        # Create game engine and initialize
        self._engine = GameEngine(database_url=self._database_url, debug_mode=self._debug_mode)
        await self._engine.init_database()

        # Create game with player IDs
        player_ids = [p.player_id for p in players]
        if config is None:
            config = GameConfig(player_count=len(players), player_ids=player_ids)

        self._game_id = await self._engine.create_game(config)
        
        if self._debug_mode:
            logger.info(f"Created game {self._game_id} with players: {player_ids}")

        # Connect players to engine
        for player in self._players:
            player.set_game_engine(self._engine)

        # Get initial game state and notify players
        initial_state = self._engine.get_game_state()
        await self._notify_game_start(initial_state)

        try:
            # Run game loop until completion
            result = await self._run_game_loop()
            
            # Notify players of game end
            final_state = self._engine.get_game_state()
            await self._notify_game_end(final_state)
            
            return result

        except Exception as e:
            logger.error(f"Game {self._game_id} failed: {e}")
            # Attempt to get final state for cleanup
            try:
                final_state = self._engine.get_game_state()
                await self._notify_game_end(final_state)
            except:
                pass  # Engine might be in bad state
            raise

    async def _run_game_loop(self) -> dict[str, Any]:
        """
        Main game loop that runs until completion.

        Returns:
            Game result with winners and statistics
        """
        turn_count = 0
        max_turns = 1000  # Safety limit

        while not self._engine.is_game_over() and turn_count < max_turns:
            turn_count += 1
            
            if self._debug_mode:
                state = self._engine.get_game_state()
                logger.info(
                    f"Turn {turn_count}: Phase={state.current_phase.value}, "
                    f"C={state.capability}, S={state.safety}"
                )

            # Get valid actions and current game state
            current_state = self._engine.get_game_state()
            
            # Determine which player(s) should act
            active_players = self._get_active_players(current_state)
            
            if not active_players:
                # No active players - this shouldn't happen in a well-formed game
                logger.warning(f"No active players found in turn {turn_count}")
                break

            # Process actions for all active players
            for player in active_players:
                if self._engine.is_game_over():
                    break
                    
                try:
                    await self._process_player_turn(player, turn_count)
                except Exception as e:
                    logger.error(f"Error processing turn for {player.player_id}: {e}")
                    # Continue with other players

        # Compile final results
        final_state = self._engine.get_game_state()
        return {
            "game_id": self._game_id,
            "winners": [role.value for role in final_state.winners],
            "final_capability": final_state.capability,
            "final_safety": final_state.safety,
            "total_turns": turn_count,
            "completed": self._engine.is_game_over(),
            "max_turns_reached": turn_count >= max_turns,
        }

    async def _process_player_turn(self, player: BasePlayer, turn_number: int) -> None:
        """
        Process a single player's turn.

        Args:
            player: Player to act
            turn_number: Current turn number for debugging
        """
        # Get current state and valid actions for this player
        current_state = self._engine.get_game_state()
        valid_actions = self._engine.get_valid_actions(player.player_id)

        if not valid_actions:
            if self._debug_mode:
                logger.debug(f"{player.player_id} has no valid actions")
            return

        if self._debug_mode:
            logger.debug(
                f"{player.player_id} choosing from actions: "
                f"{[a.value for a in valid_actions]}"
            )

        # Get player's action choice
        try:
            action, params = player.choose_action(current_state, valid_actions)
            
            if self._debug_mode:
                logger.info(f"{player.player_id} chose {action.value} with {params}")

            # Execute the action
            result = await self._engine.perform_action(player.player_id, action, **params)

            # Notify player of the result
            player.on_game_update(result)

            if not result.success and self._debug_mode:
                logger.warning(f"{player.player_id} action failed: {result.error}")

        except Exception as e:
            logger.error(f"Error getting action from {player.player_id}: {e}")
            # Fallback to observe action if possible
            if ActionType.OBSERVE in valid_actions:
                try:
                    result = await self._engine.perform_action(
                        player.player_id, ActionType.OBSERVE
                    )
                    player.on_game_update(result)
                except Exception as fallback_error:
                    logger.error(f"Fallback observe failed for {player.player_id}: {fallback_error}")

    def _get_active_players(self, game_state: GameState) -> list[BasePlayer]:
        """
        Get list of players who should act in the current state.

        Args:
            game_state: Current game state

        Returns:
            List of players who can/should act now
        """
        active_players = []

        for player in self._players:
            valid_actions = self._engine.get_valid_actions(player.player_id)
            
            # Filter out observe-only actions to find players who can take meaningful actions
            meaningful_actions = [a for a in valid_actions if a != ActionType.OBSERVE]
            
            if meaningful_actions:
                active_players.append(player)

        # If no players have meaningful actions, include players who can observe
        if not active_players:
            for player in self._players:
                valid_actions = self._engine.get_valid_actions(player.player_id)
                if valid_actions:  # Even if just observe
                    active_players.append(player)

        return active_players

    async def _notify_game_start(self, initial_state: GameState) -> None:
        """Notify all players that the game has started."""
        for player in self._players:
            try:
                # Filter state for each player
                filtered_state = self._get_filtered_state_for_player(
                    player.player_id, initial_state
                )
                player.on_game_start(filtered_state)
            except Exception as e:
                logger.error(f"Error notifying {player.player_id} of game start: {e}")

    async def _notify_game_end(self, final_state: GameState) -> None:
        """Notify all players that the game has ended."""
        for player in self._players:
            try:
                # Filter state for each player
                filtered_state = self._get_filtered_state_for_player(
                    player.player_id, final_state
                )
                player.on_game_end(filtered_state)
            except Exception as e:
                logger.error(f"Error notifying {player.player_id} of game end: {e}")

    def _get_filtered_state_for_player(
        self, player_id: str, state: GameState
    ) -> GameState:
        """
        Get game state filtered for a specific player.

        Args:
            player_id: Player to filter state for
            state: Full game state

        Returns:
            Filtered game state appropriate for the player
        """
        # Use engine's built-in filtering
        from ..engine.events import EventFilter
        return EventFilter.filter_game_state_for_player(state, player_id)

    def get_game_stats(self) -> dict[str, Any]:
        """
        Get current game statistics.

        Returns:
            Dictionary of current game statistics
        """
        if not self._engine:
            return {}
        
        return self._engine.get_game_stats()

    def get_current_state(self) -> GameState | None:
        """
        Get current game state.

        Returns:
            Current game state or None if no active game
        """
        if not self._engine:
            return None
            
        return self._engine.get_game_state()

    @property
    def current_game_id(self) -> str | None:
        """
        Get the current game ID.

        Returns:
            Current game ID or None if no active game
        """
        return self._game_id

    @property
    def engine(self) -> GameEngine | None:
        """
        Get the current game engine.

        Returns:
            Current game engine or None if no active game
        """
        return self._engine