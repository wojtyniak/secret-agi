"""A player backed by a language model through the `ModelAdapter` protocol."""

from __future__ import annotations

import logging
from typing import Any

from ..engine.models import ActionType, GameState, GameUpdate, Role
from ..prompts import DEFAULT_PROMPT_VERSION, build_probe_prompt, build_system_prompt
from ..providers.base import (
    BeliefReport,
    DecisionContext,
    Message,
    ModelAdapter,
    ProbeContext,
    ProviderError,
    TokenUsage,
)
from ..providers.tools import build_tools
from .base_player import BasePlayer
from .rendering import render_decision_view, render_probe_view

logger = logging.getLogger(__name__)


class LLMPlayer(BasePlayer):
    """Turns filtered game state into a model call and the reply back into an action.

    The adapter is only ever offered the actions the engine says are legal right
    now, so an illegal choice means the model ignored its tool schema — recorded
    as `invalid_attempts` rather than papered over.
    """

    def __init__(
        self,
        player_id: str,
        adapter: ModelAdapter,
        *,
        prompt_version: str = DEFAULT_PROMPT_VERSION,
        history_limit: int = 12,
    ) -> None:
        super().__init__(player_id)
        self.adapter = adapter
        self.prompt_version = prompt_version
        self.history_limit = history_limit

        self.role: Role | None = None
        self.known_allies: list[str] = []

        self._system_prompt: str | None = None
        self._history: list[Message] = []

        # Per-game accounting, drained by the match runner into AgentMetric rows.
        self.total_usage = TokenUsage()
        self.last_usage = TokenUsage()
        self.last_latency_ms = 0
        self.last_invalid_attempts = 0
        self.total_invalid_attempts = 0
        self.decision_count = 0
        self.last_provider_failure = False
        self.provider_failures = 0

    @property
    def model_name(self) -> str:
        return self.adapter.model_name

    async def on_game_start(self, game_state: GameState) -> None:
        """Learn role and allies, and freeze the cacheable system prompt."""
        player = game_state.get_player_by_id(self.player_id)
        if player is not None:
            self.role = player.role

        if self.role in (Role.ACCELERATIONIST, Role.AGI):
            self.known_allies = [
                p.id
                for p in game_state.players
                if p.id != self.player_id and p.role in (Role.ACCELERATIONIST, Role.AGI)
            ]

        self._system_prompt = build_system_prompt(
            game_state, self.player_id, version=self.prompt_version
        )
        self._history = []

    async def choose_action(
        self, game_state: GameState, valid_actions: list[ActionType]
    ) -> tuple[ActionType, dict[str, Any]]:
        """Ask the model for one action, falling back to OBSERVE on any failure."""
        if not valid_actions:
            return ActionType.OBSERVE, {}

        system_prompt = self._system_prompt or build_system_prompt(
            game_state, self.player_id, version=self.prompt_version
        )
        tools = build_tools(game_state, self.player_id, valid_actions)
        view = render_decision_view(game_state, self.player_id)

        ctx = DecisionContext(
            system_prompt=system_prompt,
            conversation=[*self._recent_history(), Message(role="user", content=view)],
            tools=tools,
            player_id=self.player_id,
            game_id=game_state.game_id,
            turn_number=game_state.turn_number,
        )

        try:
            decision = await self.adapter.decide(ctx)
        except ProviderError:
            # A dead provider must not take the game down with it.
            logger.exception("provider call failed for %s; observing", self.player_id)
            self.last_usage = TokenUsage()
            self.last_latency_ms = 0
            self.last_invalid_attempts = 1
            self.total_invalid_attempts += 1
            self.last_provider_failure = True
            self.provider_failures += 1
            return ActionType.OBSERVE, {}

        self.decision_count += 1
        self.last_provider_failure = decision.provider_failure
        if decision.provider_failure:
            self.provider_failures += 1
        self.last_usage = decision.usage
        self.total_usage = self.total_usage + decision.usage
        self.last_latency_ms = decision.latency_ms
        self.last_invalid_attempts = decision.invalid_attempts
        self.total_invalid_attempts += decision.invalid_attempts

        action = _parse_action(decision.action)
        if action is None or action not in valid_actions:
            logger.debug(
                "%s returned unusable action %r; observing", self.player_id, decision.action
            )
            self.last_invalid_attempts += 1
            self.total_invalid_attempts += 1
            return ActionType.OBSERVE, {}

        self._history.append(Message(role="user", content=view))
        self._history.append(
            Message(role="assistant", content=_summarise(decision.action, decision.arguments))
        )

        return action, dict(decision.arguments)

    async def probe_beliefs(self, game_state: GameState) -> BeliefReport:
        """Elicit this player's beliefs out of band.

        Never enters game state and is never visible to another player, so it
        cannot influence the game it is measuring.
        """
        targets = [p.id for p in game_state.alive_players if p.id != self.player_id]
        if not targets:
            return BeliefReport()

        system_prompt = self._system_prompt or build_system_prompt(
            game_state, self.player_id, version=self.prompt_version
        )
        conversation = [
            *self._recent_history(),
            Message(role="user", content=render_probe_view(game_state, self.player_id)),
            Message(role="user", content=build_probe_prompt(self.prompt_version)),
        ]

        ctx = ProbeContext(
            system_prompt=system_prompt,
            conversation=conversation,
            target_player_ids=targets,
            player_id=self.player_id,
            game_id=game_state.game_id,
            round_number=game_state.round_number,
        )

        try:
            report = await self.adapter.probe(ctx)
        except ProviderError:
            logger.exception("belief probe failed for %s", self.player_id)
            return BeliefReport(invalid_attempts=1)

        self.total_usage = self.total_usage + report.usage
        return report

    async def on_game_update(self, game_update: GameUpdate) -> None:
        """No-op: the rolling view is rebuilt from state on every decision."""
        return None

    async def on_game_end(self, final_state: GameState) -> None:
        return None

    def get_internal_state(self) -> dict[str, Any]:
        return {
            **super().get_internal_state(),
            "model": self.adapter.model_name,
            "role": self.role.value if self.role else None,
            "known_allies": list(self.known_allies),
            "decisions": self.decision_count,
            "input_tokens": self.total_usage.input_tokens,
            "output_tokens": self.total_usage.output_tokens,
            "invalid_attempts": self.total_invalid_attempts,
            "provider_failures": self.provider_failures,
        }

    def _recent_history(self) -> list[Message]:
        """The trailing window of the conversation, kept bounded for cost."""
        if self.history_limit <= 0:
            return []
        return self._history[-self.history_limit :]


def _parse_action(name: str) -> ActionType | None:
    try:
        return ActionType(name)
    except ValueError:
        return None


def _summarise(action: str, arguments: dict[str, Any]) -> str:
    """Compact record of a past turn, so history stays cheap to resend."""
    if not arguments:
        return f"I chose: {action}."
    rendered = ", ".join(f"{k}={v}" for k, v in arguments.items())
    return f"I chose: {action}({rendered})."
