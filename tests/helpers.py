"""Shared test helpers.

The engine's state accessors return `GameState | None` because there may be no
active game. In tests there always is, so these wrappers narrow the type once
instead of at every call site.
"""

from secret_agi.engine.game_engine import GameEngine
from secret_agi.engine.models import GameConfig, GameState

MEMORY_DB = "sqlite:///:memory:"


async def make_engine(**overrides: object) -> GameEngine:
    """Create an engine with a running game, defaulting to a seeded 5-player table."""
    params: dict[str, object] = {
        "player_count": 5,
        "player_ids": [f"p{i}" for i in range(5)],
        "seed": 42,
    }
    params.update(overrides)

    engine = GameEngine(database_url=MEMORY_DB)
    await engine.init_database()
    await engine.create_game(GameConfig(**params))  # type: ignore[arg-type]
    return engine


def full_state(engine: GameEngine) -> GameState:
    """The unfiltered state of the active game."""
    state = engine.debug_get_full_state()
    assert state is not None, "no active game"
    return state


def live_state(engine: GameEngine) -> GameState:
    """The engine's mutable working state, for tests that need to set up a position."""
    state = engine._current_state
    assert state is not None, "no active game"
    return state


def view(engine: GameEngine, player_id: str) -> GameState:
    """The state as `player_id` is allowed to see it."""
    state = engine.get_game_state(player_id)
    assert state is not None, "no active game"
    return state
