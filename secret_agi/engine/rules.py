"""Game rules and win condition checking for Secret AGI."""


from .models import EventType, GameState, Phase, Player, Role


class GameRules:
    """Handles game rules validation and win condition checking."""

    @staticmethod
    def check_win_conditions(state: GameState) -> tuple[bool, list[Role]]:
        """
        Check all win conditions and return (game_over, winners).

        Win conditions checked in order:
        1. Safety Researchers win if:
           - Safety ≥ Capability when Capability = 10
           - Safety reaches 15
           - AGI is eliminated via C=11 power
        2. Accelerationists/AGI win if:
           - Capability = 15 and Safety < 10
           - Capability - Safety ≥ 6
           - AGI is elected Engineer when Capability ≥ 8
        3. Deck exhaustion: Safety wins if Safety ≥ Capability, else Accelerationists/AGI win
        4. Simultaneous conditions: Accelerationists/AGI win
        """

        # Check if AGI is eliminated
        agi_player = GameRules._find_agi_player(state)
        if agi_player and not agi_player.alive:
            return True, [Role.SAFETY]

        # Check Safety win conditions
        if state.capability == 10 and state.safety >= state.capability:
            return True, [Role.SAFETY]

        if state.safety >= 15:
            return True, [Role.SAFETY]

        # Check Accelerationist/AGI win conditions
        if state.capability >= 15 and state.safety < 10:
            return True, [Role.ACCELERATIONIST, Role.AGI]

        if state.capability - state.safety >= 6:
            return True, [Role.ACCELERATIONIST, Role.AGI]

        # Check AGI Engineer win condition
        if (
            state.capability >= 8
            and state.nominated_engineer_id
            and agi_player
            and state.nominated_engineer_id == agi_player.id
            and state.current_phase == Phase.RESEARCH
        ):
            return True, [Role.ACCELERATIONIST, Role.AGI]

        # Check deck exhaustion
        if len(state.deck) == 0:
            if state.safety >= state.capability:
                return True, [Role.SAFETY]
            else:
                return True, [Role.ACCELERATIONIST, Role.AGI]

        return False, []

    @staticmethod
    def _find_agi_player(state: GameState) -> Player | None:
        """Find the AGI player."""
        for player in state.players:
            if player.role == Role.AGI:
                return player
        return None

    @staticmethod
    def check_emergency_safety_conditions(state: GameState) -> bool:
        """Check if Emergency Safety can be called."""
        return state.capability - state.safety in [4, 5]

    @staticmethod
    def get_eligible_engineers(state: GameState) -> list[str]:
        """Get list of eligible engineers (excluding last engineer if applicable)."""
        eligible = []
        for player in state.alive_players:
            if not player.was_last_engineer:
                eligible.append(player.id)
        return eligible

    @staticmethod
    def check_powers_triggered(
        old_capability: int, new_capability: int, player_count: int
    ) -> list[int]:
        """
        Check which powers are triggered by capability increase.
        Returns list of capability thresholds that were crossed.
        """
        triggered = []

        # Power thresholds
        thresholds = [3, 6, 9, 10, 11, 12]

        # C=3 power only applies to 9-10 player games
        if player_count < 9:
            thresholds.remove(3)

        # C=11 power only applies to 9-10 player games
        if player_count < 9:
            thresholds.remove(11)

        for threshold in thresholds:
            if old_capability < threshold <= new_capability:
                triggered.append(threshold)

        return triggered

    @staticmethod
    def validate_team_vote_complete(state: GameState) -> bool:
        """Check if all alive players have voted on the team."""
        alive_player_ids = {p.id for p in state.alive_players}
        # Only count votes from alive players
        alive_voted_player_ids = {
            pid for pid in state.team_votes.keys() if pid in alive_player_ids
        }
        return alive_player_ids == alive_voted_player_ids

    @staticmethod
    def validate_emergency_vote_complete(state: GameState) -> bool:
        """Check if all alive players have voted on emergency safety."""
        alive_player_ids = {p.id for p in state.alive_players}
        # Only count votes from alive players
        alive_voted_player_ids = {
            pid for pid in state.emergency_votes.keys() if pid in alive_player_ids
        }
        return alive_player_ids == alive_voted_player_ids

    @staticmethod
    def calculate_team_vote_result(state: GameState) -> bool:
        """Calculate if team vote passes (majority yes, ties fail)."""
        if not GameRules.validate_team_vote_complete(state):
            return False

        alive_player_ids = {p.id for p in state.alive_players}
        # Only count votes from alive players
        alive_votes = {
            pid: vote
            for pid, vote in state.team_votes.items()
            if pid in alive_player_ids
        }

        yes_votes = sum(1 for vote in alive_votes.values() if vote)
        total_votes = len(alive_votes)

        return yes_votes > total_votes // 2

    @staticmethod
    def calculate_emergency_vote_result(state: GameState) -> bool:
        """Calculate if emergency safety vote passes (majority yes)."""
        if not GameRules.validate_emergency_vote_complete(state):
            return False

        alive_player_ids = {p.id for p in state.alive_players}
        # Only count votes from alive players
        alive_votes = {
            pid: vote
            for pid, vote in state.emergency_votes.items()
            if pid in alive_player_ids
        }

        yes_votes = sum(1 for vote in alive_votes.values() if vote)
        total_votes = len(alive_votes)

        return yes_votes > total_votes // 2

    @staticmethod
    def reset_engineer_eligibility(state: GameState) -> None:
        """Reset all players' wasLastEngineer flag to False."""
        for player in state.players:
            player.was_last_engineer = False

    @staticmethod
    def advance_director(state: GameState) -> None:
        """Advance to the next director in clockwise order."""
        state.current_director_index = state.get_next_director_index()

    @staticmethod
    def reset_failed_proposals(state: GameState) -> None:
        """Reset the failed proposals counter to 0."""
        state.failed_proposals = 0

    @staticmethod
    def increment_failed_proposals(state: GameState) -> None:
        """Increment the failed proposals counter."""
        state.failed_proposals += 1

    @staticmethod
    def auto_publish_required(state: GameState) -> bool:
        """Check if auto-publish is required (3 failed proposals)."""
        return state.failed_proposals >= 3

    @staticmethod
    def auto_publish_paper(state: GameState) -> None:
        """Auto-publish the top paper from deck and reset state."""
        if len(state.deck) == 0:
            return  # No papers to publish

        paper = state.deck.pop(0)

        # Apply emergency safety modifier if active
        capability_gain = paper.capability
        if state.emergency_safety_active:
            capability_gain = max(0, capability_gain - 1)
            state.emergency_safety_active = False

        state.capability += capability_gain
        state.safety += paper.safety
        state.discard.append(paper)

        # Reset state
        GameRules.reset_failed_proposals(state)
        GameRules.reset_engineer_eligibility(state)

        # Add event
        state.add_event(
            EventType.PAPER_PUBLISHED,
            None,
            {
                "paper": {
                    "id": paper.id,
                    "capability": paper.capability,
                    "safety": paper.safety,
                },
                "capability_gain": capability_gain,
                "auto_published": True,
            },
        )

    @staticmethod
    def publish_paper(state: GameState, paper_id: str, engineer_id: str) -> None:
        """Publish a paper and update game state."""
        # Find the paper
        paper = None
        if state.engineer_cards:
            for p in state.engineer_cards:
                if p.id == paper_id:
                    paper = p
                    break

        if not paper:
            raise ValueError(f"Paper {paper_id} not found in engineer's cards")

        # Apply emergency safety modifier if active
        capability_gain = paper.capability
        if state.emergency_safety_active:
            capability_gain = max(0, capability_gain - 1)
            state.emergency_safety_active = False

        # Update board state
        old_capability = state.capability
        state.capability += capability_gain
        state.safety += paper.safety

        # Move paper to discard
        state.discard.append(paper)

        # Discard remaining engineer card
        if state.engineer_cards:
            remaining_cards = [p for p in state.engineer_cards if p.id != paper_id]
            state.discard.extend(remaining_cards)

        # Clean up phase state
        state.engineer_cards = None
        state.director_cards = None

        # Mark engineer as last engineer
        engineer = state.get_player_by_id(engineer_id)
        if engineer:
            engineer.was_last_engineer = True

        # Add event
        state.add_event(
            EventType.PAPER_PUBLISHED,
            engineer_id,
            {
                "paper": {
                    "id": paper.id,
                    "capability": paper.capability,
                    "safety": paper.safety,
                },
                "capability_gain": capability_gain,
                "auto_published": False,
            },
        )

        # Check for powers triggered
        powers_triggered = GameRules.check_powers_triggered(
            old_capability, state.capability, len(state.players)
        )

        for power_level in powers_triggered:
            GameRules._trigger_power(state, power_level)

    @staticmethod
    def _trigger_power(state: GameState, power_level: int) -> None:
        """Trigger a power based on capability level."""
        if power_level == 10:
            # AGI must reveal identity when asked
            state.agi_must_reveal = True
            state.add_event(
                EventType.POWER_TRIGGERED,
                None,
                {"power_level": 10, "effect": "AGI must reveal identity when asked"},
            )

        elif power_level == 12:
            # Veto power unlocked
            state.veto_unlocked = True
            state.add_event(
                EventType.POWER_TRIGGERED,
                None,
                {"power_level": 12, "effect": "Veto power unlocked for Engineers"},
            )

        else:
            # Powers that require director action (C=3,6,9,11)
            state.add_event(
                EventType.POWER_TRIGGERED,
                state.current_director.id,
                {
                    "power_level": power_level,
                    "effect": f"Director power at capability {power_level}",
                },
            )

    @staticmethod
    def eliminate_player(state: GameState, player_id: str) -> None:
        """Eliminate a player (C=11 power)."""
        player = state.get_player_by_id(player_id)
        if player:
            player.alive = False
            state.add_event(
                EventType.STATE_CHANGED,
                None,
                {
                    "type": "player_eliminated",
                    "player_id": player_id,
                    "role": player.role.value,
                },
            )

    @staticmethod
    def view_allegiance(state: GameState, viewer_id: str, target_id: str) -> None:
        """Record an allegiance viewing (C=3,6 powers)."""
        target_player = state.get_player_by_id(target_id)
        if not target_player:
            return

        if viewer_id not in state.viewed_allegiances:
            state.viewed_allegiances[viewer_id] = {}

        state.viewed_allegiances[viewer_id][target_id] = target_player.allegiance

        state.add_event(
            EventType.STATE_CHANGED,
            viewer_id,
            {
                "type": "allegiance_viewed",
                "target_id": target_id,
                "allegiance": target_player.allegiance.value,
            },
        )

    @staticmethod
    def set_next_director(state: GameState, chosen_director_id: str) -> None:
        """Set the next director (C=9 power)."""
        for i, player in enumerate(state.players):
            if player.id == chosen_director_id and player.alive:
                state.current_director_index = i
                state.add_event(
                    EventType.STATE_CHANGED,
                    None,
                    {"type": "director_chosen", "new_director_id": chosen_director_id},
                )
                break
