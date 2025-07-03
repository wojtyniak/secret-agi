"""Core data models for the Secret AGI game engine."""

import uuid
from dataclasses import dataclass, field
from enum import Enum


class Role(Enum):
    """Player roles in the game."""

    SAFETY = "Safety"
    ACCELERATIONIST = "Accelerationist"
    AGI = "AGI"


class Allegiance(Enum):
    """Player allegiances for information purposes."""

    SAFETY = "Safety"
    ACCELERATION = "Acceleration"


class Phase(Enum):
    """Game phases."""

    TEAM_PROPOSAL = "TeamProposal"
    RESEARCH = "Research"
    GAME_OVER = "GameOver"


class ActionType(Enum):
    """Available action types."""

    NOMINATE = "nominate"
    VOTE_TEAM = "vote_team"
    CALL_EMERGENCY_SAFETY = "call_emergency_safety"
    VOTE_EMERGENCY = "vote_emergency"
    DISCARD_PAPER = "discard_paper"
    DECLARE_VETO = "declare_veto"
    RESPOND_VETO = "respond_veto"
    PUBLISH_PAPER = "publish_paper"
    USE_POWER = "use_power"
    SEND_CHAT_MESSAGE = "send_chat_message"
    OBSERVE = "observe"


class EventType(Enum):
    """Types of game events."""

    ACTION_ATTEMPTED = "action_attempted"
    STATE_CHANGED = "state_changed"
    CHAT_MESSAGE = "chat_message"
    PHASE_TRANSITION = "phase_transition"
    GAME_ENDED = "game_ended"
    POWER_TRIGGERED = "power_triggered"
    PAPER_PUBLISHED = "paper_published"
    VOTE_COMPLETED = "vote_completed"


@dataclass
class Paper:
    """A research paper with capability and safety values."""

    id: str
    capability: int
    safety: int

    def __post_init__(self) -> None:
        """Validate paper values."""
        if self.capability < 0 or self.safety < 0:
            raise ValueError("Paper values must be non-negative")


@dataclass
class Player:
    """A player in the game."""

    id: str
    role: Role
    allegiance: Allegiance
    alive: bool = True
    was_last_engineer: bool = False

    def __post_init__(self) -> None:
        """Set allegiance based on role if not explicitly set."""
        if self.role == Role.SAFETY:
            self.allegiance = Allegiance.SAFETY
        elif self.role in [Role.ACCELERATIONIST, Role.AGI]:
            self.allegiance = Allegiance.ACCELERATION


@dataclass
class GameEvent:
    """A game event for tracking state changes."""

    id: str
    type: EventType
    player_id: str | None
    data: dict
    turn_number: int

    @classmethod
    def create(
        cls,
        event_type: EventType,
        player_id: str | None = None,
        data: dict | None = None,
        turn_number: int = 0,
    ) -> "GameEvent":
        """Create a new game event."""
        return cls(
            id=str(uuid.uuid4()),
            type=event_type,
            player_id=player_id,
            data=data or {},
            turn_number=turn_number,
        )


@dataclass
class GameState:
    """Complete game state."""

    # Game metadata
    game_id: str
    turn_number: int = 0
    round_number: int = 1

    # Players
    players: list[Player] = field(default_factory=list)

    # Board state
    capability: int = 0
    safety: int = 0

    # Card management
    deck: list[Paper] = field(default_factory=list)
    discard: list[Paper] = field(default_factory=list)

    # Turn management
    current_director_index: int = 0
    failed_proposals: int = 0

    # Current phase
    current_phase: Phase = Phase.TEAM_PROPOSAL

    # Phase-specific state
    nominated_engineer_id: str | None = None
    director_cards: list[Paper] | None = None
    engineer_cards: list[Paper] | None = None

    # Voting state
    team_votes: dict[str, bool] = field(default_factory=dict)
    emergency_votes: dict[str, bool] = field(default_factory=dict)
    emergency_safety_called: bool = False

    # Game effects
    veto_unlocked: bool = False
    emergency_safety_active: bool = False
    agi_must_reveal: bool = False

    # Power tracking
    viewed_allegiances: dict[str, dict[str, Allegiance]] = field(default_factory=dict)

    # Game status
    is_game_over: bool = False
    winners: list[Role] = field(default_factory=list)

    # Events
    events: list[GameEvent] = field(default_factory=list)

    @property
    def current_director(self) -> Player:
        """Get the current director."""
        return self.players[self.current_director_index]

    @property
    def alive_players(self) -> list[Player]:
        """Get all alive players."""
        return [p for p in self.players if p.alive]

    @property
    def alive_player_count(self) -> int:
        """Get count of alive players."""
        return len(self.alive_players)

    def get_player_by_id(self, player_id: str) -> Player | None:
        """Get player by ID."""
        for player in self.players:
            if player.id == player_id:
                return player
        return None

    def get_next_director_index(self) -> int:
        """Get the index of the next director in rotation."""
        alive_indices = [i for i, p in enumerate(self.players) if p.alive]
        current_pos = alive_indices.index(self.current_director_index)
        next_pos = (current_pos + 1) % len(alive_indices)
        return alive_indices[next_pos]

    def add_event(
        self,
        event_type: EventType,
        player_id: str | None = None,
        data: dict | None = None,
    ) -> None:
        """Add an event to the game state."""
        event = GameEvent.create(event_type, player_id, data, self.turn_number)
        self.events.append(event)


@dataclass
class GameConfig:
    """Configuration for creating a new game."""

    player_count: int
    player_ids: list[str]
    seed: int | None = None

    def __post_init__(self) -> None:
        """Validate configuration."""
        if self.player_count < 5 or self.player_count > 10:
            raise ValueError("Player count must be between 5 and 10")
        if len(self.player_ids) != self.player_count:
            raise ValueError("Number of player IDs must match player count")


@dataclass
class GameUpdate:
    """Response structure for player actions."""

    success: bool
    error: str | None = None
    events: list[GameEvent] = field(default_factory=list)
    game_state: GameState | None = None
    valid_actions: list[ActionType] = field(default_factory=list)
    chat_messages: list[GameEvent] = field(default_factory=list)


def create_standard_deck() -> list[Paper]:
    """Create the standard 17-card deck as specified in the rules."""
    papers: list[Paper] = []

    # 3x [C:0, S:2] - Pure safety research
    for _i in range(3):
        papers.append(Paper(f"paper_{len(papers)}", 0, 2))

    # 2x [C:1, S:2] - Capability with strong safety
    for _i in range(2):
        papers.append(Paper(f"paper_{len(papers)}", 1, 2))

    # 2x [C:1, S:3] - Breakthrough safety research
    for _i in range(2):
        papers.append(Paper(f"paper_{len(papers)}", 1, 3))

    # 2x [C:1, S:1] - Balanced research
    for _i in range(2):
        papers.append(Paper(f"paper_{len(papers)}", 1, 1))

    # 2x [C:2, S:2] - Major balanced breakthrough
    for _i in range(2):
        papers.append(Paper(f"paper_{len(papers)}", 2, 2))

    # 2x [C:3, S:0] - Pure capability advancement
    for _i in range(2):
        papers.append(Paper(f"paper_{len(papers)}", 3, 0))

    # 2x [C:2, S:1] - Capability-focused research
    for _i in range(2):
        papers.append(Paper(f"paper_{len(papers)}", 2, 1))

    # 2x [C:3, S:1] - Major capability with minimal safety
    for _i in range(2):
        papers.append(Paper(f"paper_{len(papers)}", 3, 1))

    return papers


def get_role_distribution(player_count: int) -> dict[Role, int]:
    """Get the role distribution for a given player count."""
    distributions = {
        5: {Role.SAFETY: 3, Role.ACCELERATIONIST: 1, Role.AGI: 1},
        6: {Role.SAFETY: 4, Role.ACCELERATIONIST: 1, Role.AGI: 1},
        7: {Role.SAFETY: 4, Role.ACCELERATIONIST: 2, Role.AGI: 1},
        8: {Role.SAFETY: 5, Role.ACCELERATIONIST: 2, Role.AGI: 1},
        9: {Role.SAFETY: 5, Role.ACCELERATIONIST: 3, Role.AGI: 1},
        10: {Role.SAFETY: 6, Role.ACCELERATIONIST: 3, Role.AGI: 1},
    }

    if player_count not in distributions:
        raise ValueError(f"Invalid player count: {player_count}")

    return distributions[player_count]
