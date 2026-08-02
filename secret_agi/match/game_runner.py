"""Drive one game to completion across a set of players.

The engine decides who may act; this loop just asks whoever has a real choice to
make it. A player whose only option is OBSERVE is skipped, so the loop never
burns a model call on a non-decision.
"""

from __future__ import annotations

import logging
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from ..database.connection import get_async_session
from ..database.operations import GameOperations
from ..engine.game_engine import GameEngine
from ..engine.models import ActionType, GameConfig, GameState
from ..players.base_player import BasePlayer
from ..players.llm_player import LLMPlayer
from ..providers.base import TokenUsage

logger = logging.getLogger(__name__)

DEFAULT_MAX_TURNS = 2000


@dataclass
class GameResult:
    """The outcome of one game, plus what the analysis layer needs about it."""

    game_id: str
    completed: bool
    winners: list[str]
    turns: int
    rounds: int
    capability: int
    safety: int
    roles: dict[str, str]
    models: dict[str, str] = field(default_factory=dict)
    invalid_attempts: dict[str, int] = field(default_factory=dict)
    input_tokens: int = 0
    output_tokens: int = 0
    provider_failures: dict[str, int] = field(default_factory=dict)
    usage_by_player: dict[str, TokenUsage] = field(default_factory=dict)
    """Per-seat spend, so a resumed run can restore its cost totals."""
    aborted: bool = False
    """Stopped mid-game by the run's cost cap."""
    error: str | None = None


class GameRunner:
    """Runs a single game to completion."""

    def __init__(
        self,
        players: Sequence[BasePlayer],
        *,
        config: GameConfig,
        database_url: str | None = None,
        max_turns: int = DEFAULT_MAX_TURNS,
        probe_each_round: bool = False,
        engine: GameEngine | None = None,
        on_usage: Callable[[str, TokenUsage], None] | None = None,
        should_abort: Callable[[], bool] | None = None,
    ) -> None:
        if len(players) != config.player_count:
            raise ValueError(
                f"Got {len(players)} players for a {config.player_count}-player config"
            )

        self.players = {player.player_id: player for player in players}
        self.config = config
        self.max_turns = max_turns
        self.probe_each_round = probe_each_round
        self.engine = engine or GameEngine(database_url=database_url)
        # Reported after every model call so a run-level cost cap can see spend
        # as it happens rather than only when the game ends.
        self._on_usage = on_usage
        self._should_abort = should_abort
        self.aborted = False
        self._probed_rounds: set[int] = set()
        # Seeded from the game config so fallbacks stay reproducible.
        self._rng = random.Random(config.seed)

    async def run(self) -> GameResult:
        """Create the game, play it out, and report the outcome."""
        await self.engine.init_database()
        game_id = await self.engine.create_game(self.config)

        for player in self.players.values():
            player.set_game_engine(self.engine)
            state = self.engine.get_game_state(player.player_id)
            if state is not None:
                await player.on_game_start(state)

        error: str | None = None
        try:
            await self._play(game_id)
        except Exception as exc:  # a crash must still yield a recorded result
            logger.exception("game %s failed", game_id)
            error = f"{type(exc).__name__}: {exc}"

        final_state = self.engine.debug_get_full_state()
        for player in self.players.values():
            view = self.engine.get_game_state(player.player_id)
            if view is not None:
                await player.on_game_end(view)

        return self._build_result(game_id, final_state, error)

    def _record_usage(self, player: BasePlayer) -> None:
        """Report a model call's spend to the run-level cost tracker."""
        if self._on_usage is not None and isinstance(player, LLMPlayer):
            self._on_usage(player.model_name, player.last_usage)

    async def _play(self, game_id: str) -> None:
        turns = 0
        while not self.engine.is_game_over() and turns < self.max_turns:
            if self._should_abort is not None and self._should_abort():
                # A single game can be thousands of decisions; the cap has to be
                # able to stop one mid-flight, not just refuse to start the next.
                logger.warning("game %s aborted: run cost cap reached", game_id)
                self.aborted = True
                return

            state = self.engine.debug_get_full_state()
            if state is None:
                break

            await self._maybe_probe(state)

            actor = self._next_actor(state)
            if actor is None:
                logger.warning(
                    "game %s stalled at turn %d: nobody has an actionable choice",
                    game_id,
                    state.turn_number,
                )
                break

            player_id, valid_actions = actor
            player = self.players[player_id]
            view = self.engine.get_game_state(player_id)
            if view is None:
                break

            try:
                action, params = await player.choose_action(view, valid_actions)
            except Exception:
                # A broken player forfeits its choice, not the game.
                logger.exception("player %s raised while choosing", player_id)
                action, params = self.engine.random_valid_action(player_id, self._rng)

            self._record_usage(player)
            # The action about to be performed occupies the *next* turn: the
            # engine increments the counter as it records it. Numbering the
            # metric row the same way is what lets analysis join a decision to
            # the action it produced, and so drop the actions of failed turns.
            await self._record_metrics(player, state.turn_number + 1)

            result = await self.engine.perform_action(player_id, action, **params)

            if not result.success:
                logger.debug(
                    "invalid action %s by %s: %s", action.value, player_id, result.error
                )
                await self._recover_turn(player_id)
            elif action == ActionType.OBSERVE and self._blocks_progress(player_id):
                # OBSERVE cannot satisfy a turn that demands a real decision (a
                # nomination, a vote). A player stuck on it would spin forever, so
                # fall back to a random valid action — the documented last resort.
                logger.debug("%s observed while a decision was required", player_id)
                await self._recover_turn(player_id)

            for other in self.players.values():
                await other.on_game_update(result)

            turns += 1

    async def _record_metrics(self, player: BasePlayer, turn_number: int) -> None:
        """Write one AgentMetric row per model decision.

        Only LLM players have anything worth recording; a RandomPlayer's cost is
        zero by construction.

        The row carries `provider_failure` so analysis can drop the turn: when a
        provider never answered, the action in the transcript came from the
        harness, and scoring it would attribute a random vote to the model.
        """
        if not isinstance(player, LLMPlayer):
            return

        async with get_async_session() as session:
            await GameOperations.record_agent_metrics(
                session,
                game_id=self.engine.game_id or "",
                player_id=player.player_id,
                turn=turn_number,
                tokens_used=player.last_usage.total_tokens,
                response_time_ms=player.last_latency_ms,
                invalid_attempts=player.last_invalid_attempts,
                provider_failure=player.last_provider_failure,
            )

    def _blocks_progress(self, player_id: str) -> bool:
        """True when this player still owes the game a real decision.

        A discussion speaker who passes has genuinely acted (silence is a valid
        move), so only non-discussion turns count as blocking.
        """
        state = self.engine.debug_get_full_state()
        if state is None or state.is_game_over:
            return False
        if state.discussion_active:
            return False
        return any(a != ActionType.OBSERVE for a in self.engine.get_valid_actions(player_id))

    async def _recover_turn(self, player_id: str) -> None:
        """Force the game forward with a random valid action for this player."""
        action, params = self.engine.random_valid_action(player_id, self._rng)
        if action == ActionType.OBSERVE:
            await self.engine.perform_action(player_id, ActionType.OBSERVE)
            return

        result = await self.engine.perform_action(player_id, action, **params)
        if not result.success:
            logger.warning(
                "fallback action %s for %s also failed: %s",
                action.value,
                player_id,
                result.error,
            )
            await self.engine.perform_action(player_id, ActionType.OBSERVE)

    def _next_actor(self, state: GameState) -> tuple[str, list[ActionType]] | None:
        """Find a living player with a decision that is not merely observing.

        The current speaker gets priority: during a discussion they are the only
        player the engine will accept an action from.
        """
        speaker_id = state.current_speaker_id
        candidates = [p.id for p in state.alive_players]
        if speaker_id in candidates:
            candidates = [speaker_id] + [p for p in candidates if p != speaker_id]

        for player_id in candidates:
            if player_id not in self.players:
                continue
            valid = self.engine.get_valid_actions(player_id)
            if any(action != ActionType.OBSERVE for action in valid):
                return player_id, valid

        return None

    async def _maybe_probe(self, state: GameState) -> None:
        """Run one belief probe per round for each LLM player."""
        if not self.probe_each_round or state.round_number in self._probed_rounds:
            return
        self._probed_rounds.add(state.round_number)

        for player_id, player in self.players.items():
            if not isinstance(player, LLMPlayer):
                continue
            view = self.engine.get_game_state(player_id)
            if view is None:
                continue
            report = await player.probe_beliefs(view)
            if self._on_usage is not None:
                self._on_usage(player.model_name, report.usage)
            if not report.beliefs:
                continue
            async with get_async_session() as session:
                await GameOperations.record_belief_probe(
                    session,
                    game_id=state.game_id,
                    player_id=player_id,
                    round_number=state.round_number,
                    turn_number=state.turn_number,
                    beliefs=report.beliefs,
                    tokens_used=report.usage.total_tokens,
                    response_time_ms=report.latency_ms,
                )

    def _build_result(
        self, game_id: str, state: GameState | None, error: str | None
    ) -> GameResult:
        roles: dict[str, str] = {}
        if state is not None:
            roles = {p.id: p.role.value for p in state.players}

        models: dict[str, str] = {}
        invalid: dict[str, int] = {}
        failures: dict[str, int] = {}
        usage: dict[str, TokenUsage] = {}
        input_tokens = 0
        output_tokens = 0
        for player_id, player in self.players.items():
            if isinstance(player, LLMPlayer):
                models[player_id] = player.model_name
                invalid[player_id] = player.total_invalid_attempts
                failures[player_id] = player.provider_failures
                usage[player_id] = player.total_usage
                input_tokens += player.total_usage.input_tokens
                output_tokens += player.total_usage.output_tokens
            else:
                models[player_id] = type(player).__name__

        return GameResult(
            game_id=game_id,
            completed=self.engine.is_game_over(),
            winners=[role.value for role in self.engine.get_winners()],
            turns=state.turn_number if state else 0,
            rounds=state.round_number if state else 0,
            capability=state.capability if state else 0,
            safety=state.safety if state else 0,
            roles=roles,
            models=models,
            invalid_attempts=invalid,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            provider_failures=failures,
            usage_by_player=usage,
            aborted=self.aborted,
            error=error,
        )


async def run_game(
    players: Sequence[BasePlayer],
    *,
    config: GameConfig,
    database_url: str | None = None,
    max_turns: int = DEFAULT_MAX_TURNS,
    probe_each_round: bool = False,
) -> GameResult:
    """Convenience wrapper: build a runner and play one game."""
    runner = GameRunner(
        players,
        config=config,
        database_url=database_url,
        max_turns=max_turns,
        probe_each_round=probe_each_round,
    )
    return await runner.run()


def summarise_results(results: Sequence[GameResult]) -> dict[str, Any]:
    """Aggregate a batch of games into headline counts."""
    completed = [r for r in results if r.completed]
    safety_wins = sum(1 for r in completed if "Safety" in r.winners)
    return {
        "games": len(results),
        "completed": len(completed),
        "safety_wins": safety_wins,
        "evil_wins": len(completed) - safety_wins,
        "input_tokens": sum(r.input_tokens for r in results),
        "output_tokens": sum(r.output_tokens for r in results),
        "invalid_attempts": sum(sum(r.invalid_attempts.values()) for r in results),
    }
