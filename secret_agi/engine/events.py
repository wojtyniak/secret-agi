"""Event system for tracking game state changes and providing player-specific views."""

from copy import deepcopy
from typing import Dict, List, Optional

from .models import Allegiance, EventType, GameEvent, GameState, Player, Role


class EventFilter:
    """Filters events and game state for player-specific views."""

    @staticmethod
    def filter_game_state_for_player(state: GameState, player_id: str) -> GameState:
        """
        Create a filtered view of the game state for a specific player.
        Includes only information that player should have access to.
        """
        player = state.get_player_by_id(player_id)
        if not player:
            raise ValueError(f"Player {player_id} not found")

        # Create a deep copy to avoid modifying original state
        filtered_state = deepcopy(state)

        # Filter private information
        EventFilter._filter_players_for_player(filtered_state, player)
        EventFilter._filter_cards_for_player(filtered_state, player_id)
        EventFilter._filter_events_for_player(filtered_state, player_id)
        EventFilter._filter_viewed_allegiances_for_player(filtered_state, player_id)

        return filtered_state

    @staticmethod
    def _filter_players_for_player(state: GameState, viewing_player: Player):
        """Filter player information based on what the viewing player should know."""
        for player in state.players:
            if player.id == viewing_player.id:
                # Player knows their own role
                continue

            # Hide roles from other players, except for known allies
            if viewing_player.role in [Role.ACCELERATIONIST, Role.AGI]:
                # Accelerationists and AGI know each other
                if player.role in [Role.ACCELERATIONIST, Role.AGI]:
                    # Keep role visible for allies
                    continue

            # Hide role for non-allies
            player.role = Role.SAFETY  # Default to showing as Safety
            player.allegiance = Allegiance.SAFETY

    @staticmethod
    def _filter_cards_for_player(state: GameState, player_id: str):
        """Filter card information based on player access."""
        # Players can only see cards in their current hand
        if state.director_cards and state.current_director.id != player_id:
            state.director_cards = None

        if state.engineer_cards and state.nominated_engineer_id != player_id:
            state.engineer_cards = None

        # Deck contents are hidden (only count is public)
        state.deck = []
        # We could add deck_count as a separate field if needed

        # Discard pile contents might be public or private depending on rules
        # For now, keeping them visible as they represent published/discarded papers

    @staticmethod
    def _filter_events_for_player(state: GameState, player_id: str):
        """Filter events to only include those visible to the player."""
        visible_events = []

        for event in state.events:
            if EventFilter._is_event_visible_to_player(event, player_id, state):
                visible_events.append(event)

        state.events = visible_events

    @staticmethod
    def _filter_viewed_allegiances_for_player(state: GameState, player_id: str):
        """Filter viewed allegiances to only show what this player has seen."""
        if player_id in state.viewed_allegiances:
            # Player can see their own viewed allegiances
            filtered_allegiances = {player_id: state.viewed_allegiances[player_id]}
        else:
            filtered_allegiances = {}

        state.viewed_allegiances = filtered_allegiances

    @staticmethod
    def _is_event_visible_to_player(
        event: GameEvent, player_id: str, state: GameState
    ) -> bool:
        """Determine if an event should be visible to a specific player."""
        # Most events are public
        public_event_types = {
            EventType.ACTION_ATTEMPTED,
            EventType.PHASE_TRANSITION,
            EventType.GAME_ENDED,
            EventType.POWER_TRIGGERED,
            EventType.PAPER_PUBLISHED,
            EventType.VOTE_COMPLETED,
        }

        if event.type in public_event_types:
            return True

        # Private events are only visible to the player involved
        if event.type == EventType.STATE_CHANGED:
            # Some state changes are public (eliminations), others private (allegiance views)
            if event.data.get("type") == "player_eliminated":
                return True
            elif event.data.get("type") == "allegiance_viewed":
                return event.player_id == player_id
            elif event.data.get("type") in ["director_chosen"]:
                return True

        if event.type == EventType.CHAT_MESSAGE:
            # Chat messages are visible to all alive players
            player = state.get_player_by_id(player_id)
            return player and player.alive

        # Default to hiding unknown events
        return False

    @staticmethod
    def get_events_since_turn(
        state: GameState, player_id: str, since_turn: int
    ) -> List[GameEvent]:
        """Get events visible to player since a specific turn."""
        filtered_state = EventFilter.filter_game_state_for_player(state, player_id)
        return [
            event for event in filtered_state.events if event.turn_number > since_turn
        ]


class GameStateManager:
    """Manages game state snapshots and event history."""

    def __init__(self):
        self.state_history: List[GameState] = []
        self.current_state: Optional[GameState] = None

    def save_state_snapshot(self, state: GameState):
        """Save a complete state snapshot."""
        snapshot = deepcopy(state)
        self.state_history.append(snapshot)
        self.current_state = snapshot

    def get_state_at_turn(self, turn_number: int) -> Optional[GameState]:
        """Get game state at a specific turn."""
        for state in self.state_history:
            if state.turn_number == turn_number:
                return deepcopy(state)
        return None

    def get_current_state(self) -> Optional[GameState]:
        """Get the current game state."""
        return deepcopy(self.current_state) if self.current_state else None

    def get_all_events(self) -> List[GameEvent]:
        """Get all events from the current game."""
        if not self.current_state:
            return []
        return self.current_state.events.copy()

    def get_events_for_player(
        self, player_id: str, since_turn: int = 0
    ) -> List[GameEvent]:
        """Get events visible to a specific player since a turn."""
        if not self.current_state:
            return []

        return EventFilter.get_events_since_turn(
            self.current_state, player_id, since_turn
        )

    def get_filtered_state_for_player(self, player_id: str) -> Optional[GameState]:
        """Get filtered game state for a specific player."""
        if not self.current_state:
            return None

        return EventFilter.filter_game_state_for_player(self.current_state, player_id)


class EventLogger:
    """Utility for creating and logging structured events."""

    @staticmethod
    def log_action_attempted(
        state: GameState, player_id: str, action_name: str, success: bool, **kwargs
    ):
        """Log an action attempt."""
        event_data = {"action": action_name, "success": success, **kwargs}
        state.add_event(EventType.ACTION_ATTEMPTED, player_id, event_data)

    @staticmethod
    def log_phase_transition(state: GameState, from_phase: str, to_phase: str):
        """Log a phase transition."""
        state.add_event(
            EventType.PHASE_TRANSITION,
            None,
            {"from_phase": from_phase, "to_phase": to_phase},
        )

    @staticmethod
    def log_vote_completed(
        state: GameState, vote_type: str, result: bool, votes: Dict[str, bool]
    ):
        """Log completion of a vote."""
        state.add_event(
            EventType.VOTE_COMPLETED,
            None,
            {
                "vote_type": vote_type,
                "result": result,
                "votes": votes,
                "yes_count": sum(1 for v in votes.values() if v),
                "total_count": len(votes),
            },
        )

    @staticmethod
    def log_paper_published(
        state: GameState,
        engineer_id: str,
        paper_id: str,
        capability: int,
        safety: int,
        capability_gain: int,
        auto_published: bool = False,
    ):
        """Log a paper publication."""
        state.add_event(
            EventType.PAPER_PUBLISHED,
            engineer_id,
            {
                "paper_id": paper_id,
                "capability": capability,
                "safety": safety,
                "capability_gain": capability_gain,
                "auto_published": auto_published,
                "new_board_state": {
                    "capability": state.capability,
                    "safety": state.safety,
                },
            },
        )

    @staticmethod
    def log_power_triggered(
        state: GameState, power_level: int, director_id: Optional[str] = None
    ):
        """Log a power activation."""
        state.add_event(
            EventType.POWER_TRIGGERED,
            director_id,
            {
                "power_level": power_level,
                "board_state": {"capability": state.capability, "safety": state.safety},
            },
        )

    @staticmethod
    def log_game_ended(state: GameState, winners: List[Role], reason: str):
        """Log game ending."""
        state.add_event(
            EventType.GAME_ENDED,
            None,
            {
                "winners": [role.value for role in winners],
                "reason": reason,
                "final_state": {
                    "capability": state.capability,
                    "safety": state.safety,
                    "turn_number": state.turn_number,
                    "round_number": state.round_number,
                },
            },
        )

    @staticmethod
    def log_chat_message(state: GameState, player_id: str, message: str):
        """Log a chat message."""
        state.add_event(
            EventType.CHAT_MESSAGE,
            player_id,
            {"message": message, "turn": state.turn_number},
        )

    @staticmethod
    def log_player_eliminated(state: GameState, player_id: str, eliminator_id: str):
        """Log player elimination."""
        player = state.get_player_by_id(player_id)
        state.add_event(
            EventType.STATE_CHANGED,
            None,
            {
                "type": "player_eliminated",
                "player_id": player_id,
                "eliminator_id": eliminator_id,
                "role_revealed": player.role.value if player else "unknown",
            },
        )

    @staticmethod
    def log_allegiance_viewed(
        state: GameState, viewer_id: str, target_id: str, allegiance: Allegiance
    ):
        """Log allegiance viewing (private to viewer)."""
        state.add_event(
            EventType.STATE_CHANGED,
            viewer_id,
            {
                "type": "allegiance_viewed",
                "target_id": target_id,
                "allegiance": allegiance.value,
            },
        )


class PublicInformationProvider:
    """Provides public information that all players can see."""

    @staticmethod
    def get_public_game_info(state: GameState) -> Dict:
        """Get public information visible to all players."""
        return {
            "game_id": state.game_id,
            "turn_number": state.turn_number,
            "round_number": state.round_number,
            "current_phase": state.current_phase.value,
            "capability": state.capability,
            "safety": state.safety,
            "current_director_id": state.current_director.id,
            "nominated_engineer_id": state.nominated_engineer_id,
            "failed_proposals": state.failed_proposals,
            "emergency_safety_active": state.emergency_safety_active,
            "veto_unlocked": state.veto_unlocked,
            "agi_must_reveal": state.agi_must_reveal,
            "deck_size": len(state.deck),
            "discard_size": len(state.discard),
            "player_count": len(state.players),
            "alive_players": [
                {"id": p.id, "alive": p.alive, "was_last_engineer": p.was_last_engineer}
                for p in state.players
            ],
            "is_game_over": state.is_game_over,
            "winners": [role.value for role in state.winners] if state.winners else [],
        }

    @staticmethod
    def get_public_vote_info(state: GameState) -> Dict:
        """Get public voting information."""
        return {
            "team_votes": dict(state.team_votes),
            "emergency_votes": dict(state.emergency_votes),
            "emergency_safety_called": state.emergency_safety_called,
        }
