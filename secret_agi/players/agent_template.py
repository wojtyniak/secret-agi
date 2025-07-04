"""
Template for implementing your own Secret AGI agent.

Copy this file to your_agent.py and implement the methods below.
"""

from typing import Any

from ..engine.models import ActionType, GameState, GameUpdate, Role
from .base_player import BasePlayer


class YourAgent(BasePlayer):
    """
    Template for your Secret AGI agent implementation.
    
    This class provides a starting point for implementing your own LLM-based
    or rule-based agent for playing Secret AGI.
    
    Usage:
        1. Copy this file to your_agent.py
        2. Implement the choose_action method with your decision logic
        3. Add any LLM integration, prompting, or strategy logic
        4. Import and test your agent in test_your_agents.py
    """

    def __init__(self, player_id: str):
        super().__init__(player_id)
        
        # Add your agent's internal state here
        self.role: Role | None = None
        self.known_allies: list[str] = []
        self.game_history: list[dict[str, Any]] = []
        
        # TODO: Add your LLM client, prompts, or other strategy components
        # self.llm_client = YourLLMClient()
        # self.system_prompt = "You are playing Secret AGI..."

    def choose_action(
        self, game_state: GameState, valid_actions: list[ActionType]
    ) -> tuple[ActionType, dict[str, Any]]:
        """
        Choose an action based on the current game state.
        
        This is where you implement your agent's decision-making logic.
        You can use LLMs, rule-based systems, or any other approach.
        
        Args:
            game_state: Current game state (filtered for this player)
            valid_actions: List of actions this player can take
            
        Returns:
            Tuple of (action_type, action_parameters)
            
        Example returns:
            return (ActionType.NOMINATE, {"target_id": "player_2"})
            return (ActionType.VOTE_TEAM, {"vote": True})
            return (ActionType.PUBLISH_PAPER, {"paper_id": "paper_123"})
            return (ActionType.OBSERVE, {})
        """
        # TODO: Implement your decision logic here
        
        # Example: Simple rule-based logic (replace with your implementation)
        
        # If you can nominate, nominate the first eligible player
        if ActionType.NOMINATE in valid_actions:
            eligible_players = [
                p.id for p in game_state.alive_players 
                if not p.was_last_engineer and p.id != self.player_id
            ]
            if eligible_players:
                return ActionType.NOMINATE, {"target_id": eligible_players[0]}
        
        # If you can vote, vote yes (you might want better logic here)
        if ActionType.VOTE_TEAM in valid_actions:
            return ActionType.VOTE_TEAM, {"vote": True}
        
        if ActionType.VOTE_EMERGENCY in valid_actions:
            return ActionType.VOTE_EMERGENCY, {"vote": True}
        
        # If you're director and need to discard a paper
        if ActionType.DISCARD_PAPER in valid_actions and game_state.director_cards:
            # Choose first paper (you might want better logic)
            return ActionType.DISCARD_PAPER, {"paper_id": game_state.director_cards[0].id}
        
        # If you're engineer and need to publish a paper
        if ActionType.PUBLISH_PAPER in valid_actions and game_state.engineer_cards:
            # Choose first paper (you might want better logic)
            return ActionType.PUBLISH_PAPER, {"paper_id": game_state.engineer_cards[0].id}
        
        # If you can call emergency safety and capability is high
        if (ActionType.CALL_EMERGENCY_SAFETY in valid_actions and 
            game_state.capability - game_state.safety >= 4):
            return ActionType.CALL_EMERGENCY_SAFETY, {}
        
        # If you can declare veto (and want to)
        if ActionType.DECLARE_VETO in valid_actions:
            # Example: only veto if the papers look dangerous
            return ActionType.DECLARE_VETO, {}
        
        # If director is asking about your veto
        if ActionType.RESPOND_VETO in valid_actions:
            # Example: disagree with veto to keep game moving
            return ActionType.RESPOND_VETO, {"agree": False}
        
        # Default to observe if no other actions make sense
        return ActionType.OBSERVE, {}

    def on_game_start(self, game_state: GameState) -> None:
        """
        Called when the game starts.
        
        Use this to learn your role and identify known allies.
        """
        # Find your role
        for player in game_state.players:
            if player.id == self.player_id:
                self.role = player.role
                break
        
        # Identify known allies (Accelerationists and AGI know each other)
        if self.role in [Role.ACCELERATIONIST, Role.AGI]:
            for player in game_state.players:
                if (player.id != self.player_id and 
                    player.role in [Role.ACCELERATIONIST, Role.AGI]):
                    self.known_allies.append(player.id)
        
        # TODO: Add your initialization logic here
        # - Set up prompts based on role
        # - Initialize strategy parameters
        # - Prepare LLM context
        
        print(f"🤖 {self.player_id} starting as {self.role.value}")
        if self.known_allies:
            print(f"   Known allies: {self.known_allies}")

    def on_game_update(self, game_update: GameUpdate) -> None:
        """
        Called after each action with the game update.
        
        Use this to track game events and update your strategy.
        """
        # Track significant events
        if game_update.events:
            for event in game_update.events:
                self.game_history.append({
                    "type": event.type.value,
                    "data": event.data
                })
        
        # TODO: Add your update logic here
        # - Update internal game model
        # - Adjust strategy based on events
        # - Update LLM context with new information

    def on_game_end(self, final_state: GameState) -> None:
        """
        Called when the game ends.
        
        Use this for cleanup or learning from the game outcome.
        """
        winners = [role.value for role in final_state.winners]
        my_team_won = (
            (self.role == Role.SAFETY and "SAFETY" in winners) or
            (self.role in [Role.ACCELERATIONIST, Role.AGI] and 
             any(w in ["ACCELERATIONIST", "AGI"] for w in winners))
        )
        
        print(f"🏁 {self.player_id} game ended - Winners: {winners}")
        print(f"   My team {'won' if my_team_won else 'lost'}!")
        
        # TODO: Add your cleanup/learning logic here
        # - Save game results for training
        # - Update strategy parameters
        # - Log performance metrics

    def get_internal_state(self) -> dict[str, Any]:
        """
        Get the agent's internal state for debugging/analysis.
        
        This is useful for understanding what your agent is thinking.
        """
        return {
            **super().get_internal_state(),
            "role": self.role.value if self.role else None,
            "known_allies": self.known_allies,
            "game_history_length": len(self.game_history),
            "recent_events": self.game_history[-5:] if self.game_history else [],
            # TODO: Add your internal state info here
            # "current_strategy": self.current_strategy,
            # "confidence": self.confidence_level,
            # "llm_tokens_used": self.token_count,
        }


# TODO: Add additional agent classes here
# class AdvancedAgent(BasePlayer):
#     """Your more sophisticated agent implementation."""
#     pass

# class SpecialistAgent(BasePlayer):
#     """Agent specialized for a particular role or strategy."""
#     pass