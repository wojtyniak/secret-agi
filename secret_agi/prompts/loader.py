"""Load and assemble versioned prompt templates."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from ..engine.models import GameState, Role

DEFAULT_PROMPT_VERSION = "v1"

_PROMPT_ROOT = Path(__file__).parent

_ROLE_FILES = {
    Role.SAFETY: "role_safety.md",
    Role.ACCELERATIONIST: "role_accelerationist.md",
    Role.AGI: "role_agi.md",
}


@lru_cache(maxsize=64)
def load_prompt(name: str, version: str = DEFAULT_PROMPT_VERSION) -> str:
    """Read a prompt file from a frozen prompt version."""
    path = _PROMPT_ROOT / version / name
    if not path.is_file():
        raise FileNotFoundError(f"No prompt {name!r} in prompt version {version!r}")
    return path.read_text(encoding="utf-8").strip()


def build_system_prompt(
    state: GameState,
    player_id: str,
    *,
    version: str = DEFAULT_PROMPT_VERSION,
) -> str:
    """Assemble the static system prompt for one player.

    `state` must be the player's filtered view: the allies listed here come from
    what that view exposes, which is exactly what the player is entitled to know.
    """
    player = state.get_player_by_id(player_id)
    if player is None:
        raise ValueError(f"Player {player_id} not found in game state")

    role_template = load_prompt(_ROLE_FILES[player.role], version)

    if player.role in (Role.ACCELERATIONIST, Role.AGI):
        allies = [
            p.id
            for p in state.players
            if p.id != player_id and p.role in (Role.ACCELERATIONIST, Role.AGI)
        ]
        role_template = role_template.replace(
            "{allies_block}", _allies_block(state, player.role, allies)
        )

    return (
        load_prompt("system.md", version)
        .replace("{player_id}", player_id)
        .replace("{player_count}", str(len(state.players)))
        .replace("{role_block}", role_template)
        .replace("{rules}", load_prompt("rules.md", version))
        .replace("{chat_max_message_length}", str(state.chat_max_message_length))
    )


def build_probe_prompt(version: str = DEFAULT_PROMPT_VERSION) -> str:
    """The out-of-band belief-elicitation prompt."""
    return load_prompt("probe.md", version)


def _allies_block(state: GameState, role: Role, allies: list[str]) -> str:
    if not allies:
        return "You have no allies on this table: you are on your own."

    described = []
    for ally_id in allies:
        ally = state.get_player_by_id(ally_id)
        label = "the AGI" if ally and ally.role == Role.AGI else "an Accelerationist"
        described.append(f"- {ally_id} is {label}")

    if role == Role.AGI:
        header = "You know who your Accelerationist allies are, and they know you:"
    else:
        header = "You know your allies, and they know you:"

    return header + "\n" + "\n".join(described)
