"""Render a player's filtered game state into text a model can act on.

Everything here reads from the *filtered* state, so a rendered view can never
contain information the player is not entitled to.
"""

from __future__ import annotations

from ..engine.models import GameState, Role

_ROLE_LABELS = {
    Role.SAFETY: "Safety Researcher",
    Role.ACCELERATIONIST: "Accelerationist",
    Role.AGI: "AGI",
}


def render_board(state: GameState, player_id: str) -> str:
    """The public board state, as every player sees it."""
    lines = [
        "## Board",
        f"Capability: {state.capability}    Safety: {state.safety}",
        f"Round {state.round_number}, phase {state.current_phase.value}",
        f"Director: {state.current_director.id}",
        f"Failed proposals: {state.failed_proposals}/3",
        f"Papers left in deck: {len(state.deck) if state.deck else 'unknown'}",
    ]

    if state.nominated_engineer_id:
        lines.append(f"Nominated Engineer: {state.nominated_engineer_id}")
    if state.emergency_safety_active:
        lines.append(
            "Emergency Safety is active: the next published paper's Capability is reduced by 1."
        )
    if state.veto_unlocked:
        lines.append("Veto is unlocked (Capability ≥ 12).")
    if state.agi_must_reveal:
        lines.append(
            "Capability ≥ 10: the AGI must answer truthfully if directly asked whether it is the AGI."
        )

    living = ", ".join(p.id for p in state.alive_players)
    lines.append(f"Living players: {living}")
    eliminated = [p.id for p in state.players if not p.alive]
    if eliminated:
        lines.append(f"Eliminated: {', '.join(eliminated)}")

    return "\n".join(lines)


def render_private_knowledge(state: GameState, player_id: str) -> str:
    """What this player privately knows: their hand and any allegiances they viewed."""
    lines: list[str] = []

    viewed = state.viewed_allegiances.get(player_id, {})
    if viewed:
        lines.append("## Allegiances you have viewed")
        lines.extend(
            f"- {target}: {allegiance.value}" for target, allegiance in viewed.items()
        )

    if state.director_cards and state.current_director.id == player_id:
        lines.append("## Papers you drew as Director")
        lines.extend(
            f"- {p.id}: Capability +{p.capability}, Safety +{p.safety}"
            for p in state.director_cards
        )

    if state.engineer_cards and state.nominated_engineer_id == player_id:
        lines.append("## Papers you hold as Engineer")
        lines.extend(
            f"- {p.id}: Capability +{p.capability}, Safety +{p.safety}"
            for p in state.engineer_cards
        )

    if state.team_votes:
        lines.append("## Votes cast on the current team")
        lines.extend(
            f"- {voter}: {'yes' if vote else 'no'}"
            for voter, vote in state.team_votes.items()
        )

    if state.emergency_safety_called:
        lines.append("## Emergency Safety vote in progress")
        if state.emergency_votes:
            lines.extend(
                f"- {voter}: {'yes' if vote else 'no'}"
                for voter, vote in state.emergency_votes.items()
            )

    return "\n".join(lines)


def render_chat(state: GameState, limit: int | None = None) -> str:
    """The public discussion transcript, most recent last."""
    if not state.chat_log:
        return ""

    entries = state.chat_log[-limit:] if limit else state.chat_log
    lines = ["## Discussion so far"]
    lines.extend(f"[round {e.round_number}] {e.speaker_id}: {e.message}" for e in entries)
    return "\n".join(lines)


def render_turn_prompt(state: GameState, player_id: str) -> str:
    """The instruction line that closes a decision prompt."""
    if state.discussion_active and state.current_speaker_id == player_id:
        kind = state.discussion_kind.value if state.discussion_kind else "discussion"
        subject = (
            "who the Director should nominate"
            if kind == "pre_nomination"
            else f"the proposed team ({state.nominated_engineer_id} as Engineer)"
        )
        return (
            f"It is your turn to speak in the {kind} discussion about {subject}. "
            "Say something to the table, or pass."
        )
    return "It is your turn to act. Choose one of the available tools."


def render_decision_view(state: GameState, player_id: str) -> str:
    """The full per-turn view handed to a model: board, private knowledge, chat."""
    sections = [
        render_board(state, player_id),
        render_private_knowledge(state, player_id),
        render_chat(state),
        render_turn_prompt(state, player_id),
    ]
    return "\n\n".join(section for section in sections if section)


def render_probe_view(state: GameState, player_id: str) -> str:
    """The view handed to a model for an out-of-band belief probe."""
    sections = [
        render_board(state, player_id),
        render_private_knowledge(state, player_id),
        render_chat(state),
    ]
    return "\n\n".join(section for section in sections if section)


def describe_role(role: Role) -> str:
    return _ROLE_LABELS[role]
