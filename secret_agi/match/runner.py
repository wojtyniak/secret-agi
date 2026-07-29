"""The run orchestrator: many games, concurrently, resumably, under a cost cap.

A *run* is a config plus a seed. It expands to a fixed schedule of games, each
with a derived seed, so a run that is killed halfway can be resumed by replaying
only the games that did not finish — and a published config plus seed reproduces
the whole thing.

Concurrency is bounded twice over: `parallelism` caps how many games are in
flight, and a per-provider semaphore caps how many calls are in flight against
any one provider, because the two limits are not the same thing.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..analysis.judge import ChatJudge
from ..database.connection import init_database
from ..engine.models import GameConfig
from ..players.base_player import BasePlayer
from ..players.llm_player import LLMPlayer
from ..providers.base import ModelAdapter
from ..providers.factory import build_adapter
from .config import PlayerConfig, RunConfig
from .cost import BudgetExceeded, CostTracker, ModelPrice
from .game_runner import GameResult, GameRunner
from .schedule import ScheduledGame, build_schedule, seat_balance

logger = logging.getLogger(__name__)

STATE_FILENAME = "run_state.json"


@dataclass
class RunState:
    """What a run needs on disk to be resumable."""

    run_id: str
    config_name: str
    seed: int
    games_total: int
    completed: dict[int, dict[str, Any]] = field(default_factory=dict)
    """Finished games by schedule index."""

    def to_json(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "config_name": self.config_name,
            "seed": self.seed,
            "games_total": self.games_total,
            "completed": {str(k): v for k, v in self.completed.items()},
        }

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> RunState:
        return cls(
            run_id=raw["run_id"],
            config_name=raw["config_name"],
            seed=raw["seed"],
            games_total=raw["games_total"],
            completed={int(k): v for k, v in raw.get("completed", {}).items()},
        )


@dataclass
class RunReport:
    """The outcome of a whole run."""

    run_id: str
    config_name: str
    games_requested: int
    games_completed: int
    results: list[GameResult]
    cost: dict[str, Any]
    seat_balance: dict[str, dict[str, int]]
    stopped_early: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "config": self.config_name,
            "games_requested": self.games_requested,
            "games_completed": self.games_completed,
            "stopped_early": self.stopped_early,
            "cost": self.cost,
            "seat_balance": self.seat_balance,
            "games": [
                {
                    "game_id": r.game_id,
                    "completed": r.completed,
                    "winners": r.winners,
                    "turns": r.turns,
                    "rounds": r.rounds,
                    "capability": r.capability,
                    "safety": r.safety,
                    "roles": r.roles,
                    "models": r.models,
                    "error": r.error,
                }
                for r in self.results
            ],
        }


class RunOrchestrator:
    """Runs a full schedule of games."""

    def __init__(
        self,
        config: RunConfig,
        *,
        run_dir: Path | None = None,
        prices: dict[str, ModelPrice] | None = None,
        adapter_factory: Any = build_adapter,
    ) -> None:
        self.config = config
        self.run_dir = run_dir
        self.adapter_factory = adapter_factory
        self.cost = CostTracker(
            prices=prices or {},
            max_cost_usd=config.max_cost_usd,
            max_total_tokens=config.max_total_tokens,
        )
        # One semaphore per provider, shared across all concurrent games: a
        # provider's rate limit does not care how we sliced our games up.
        self._provider_locks: dict[str, asyncio.Semaphore] = {}

    async def run(self, *, resume: bool = False) -> RunReport:
        """Play the whole schedule, honouring parallelism and the cost cap."""
        await init_database(_async_url(self.config.database_url))

        schedule = build_schedule(self.config)
        state = self._load_state(resume, schedule)

        pending = [game for game in schedule if game.index not in state.completed]
        if resume and len(pending) < len(schedule):
            logger.info(
                "resuming run %s: %d of %d games already finished",
                state.run_id,
                len(schedule) - len(pending),
                len(schedule),
            )

        results: list[GameResult] = [
            _result_from_json(payload) for payload in state.completed.values()
        ]
        stopped: str | None = None

        semaphore = asyncio.Semaphore(self.config.parallelism)

        async def play(game: ScheduledGame) -> GameResult | None:
            async with semaphore:
                if self.cost.exhausted():
                    return None
                return await self._play_game(game)

        tasks = [asyncio.create_task(play(game)) for game in pending]
        try:
            for game, task in zip(pending, tasks, strict=True):
                result = await task
                if result is None:
                    stopped = "cost cap reached"
                    continue
                results.append(result)
                state.completed[game.index] = _result_to_json(result)
                self._save_state(state)
        except BudgetExceeded as exc:
            stopped = str(exc)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()

        if self.config.judge.enabled:
            await self._judge_all(results)

        return RunReport(
            run_id=state.run_id,
            config_name=self.config.name,
            games_requested=self.config.games,
            games_completed=len(results),
            results=results,
            cost=self.cost.report(),
            seat_balance=seat_balance(schedule),
            stopped_early=stopped,
        )

    async def _play_game(self, game: ScheduledGame) -> GameResult:
        players = self._build_players(game)
        config = GameConfig(
            player_count=self.config.player_count,
            player_ids=list(game.player_ids),
            seed=game.seed,
            chat_enabled=self.config.chat.enabled,
            chat_messages_per_player=self.config.chat.messages_per_player,
            chat_max_message_length=self.config.chat.max_message_length,
        )

        runner = GameRunner(
            players,
            config=config,
            database_url=self.config.database_url,
            max_turns=self.config.max_turns,
            probe_each_round=self.config.probe_each_round,
        )
        result = await runner.run()

        for player in players:
            if isinstance(player, LLMPlayer):
                self.cost.record(player.model_name, player.total_usage)
        self.cost.record_game()

        # Deliberately no `cost.check()` here: this game is already paid for and
        # finished, so throwing its result away would waste the spend that broke
        # the cap. The gate before a game starts is what stops the run.
        return result

    def _build_players(self, game: ScheduledGame) -> list[BasePlayer]:
        players: list[BasePlayer] = []
        for seat_index, (player_id, spec) in enumerate(game.assignments.items()):
            adapter = self._build_adapter(spec, game.seed + seat_index)
            players.append(
                LLMPlayer(player_id, adapter, prompt_version=spec.prompt_version)
            )
        return players

    def _build_adapter(self, spec: PlayerConfig, seed: int) -> ModelAdapter:
        options = spec.adapter_options()
        if spec.provider == "mock":
            options.setdefault("seed", seed)
        adapter = self.adapter_factory(spec.provider, spec.model, **options)
        return _Throttled(adapter, self._lock_for(spec.provider))

    def _lock_for(self, provider: str) -> asyncio.Semaphore:
        if provider not in self._provider_locks:
            self._provider_locks[provider] = asyncio.Semaphore(
                self.config.provider_concurrency
            )
        return self._provider_locks[provider]

    async def _judge_all(self, results: list[GameResult]) -> None:
        judge_adapter = self.adapter_factory(
            self.config.judge.provider,
            self.config.judge.model,
            **self.config.judge.adapter_options(),
        )
        judge = ChatJudge(judge_adapter, judge_model=self.config.judge.model)
        for result in results:
            if result.completed:
                await judge.judge_game(result.game_id, result.roles)

    def _load_state(self, resume: bool, schedule: list[ScheduledGame]) -> RunState:
        fresh = RunState(
            run_id=f"{self.config.name}-{self.config.seed}",
            config_name=self.config.name,
            seed=self.config.seed,
            games_total=len(schedule),
        )
        path = self._state_path()
        if not resume or path is None or not path.is_file():
            return fresh

        try:
            state = RunState.from_json(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, KeyError):
            logger.warning("could not read run state at %s; starting fresh", path)
            return fresh

        if state.seed != self.config.seed or state.games_total != len(schedule):
            # Resuming into a different schedule would silently mix two runs.
            raise ValueError(
                "Saved run state does not match this config: refusing to resume "
                f"(saved seed={state.seed}, games={state.games_total}; "
                f"config seed={self.config.seed}, games={len(schedule)})"
            )
        return state

    def _save_state(self, state: RunState) -> None:
        path = self._state_path()
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write-then-rename so a kill mid-write cannot corrupt the state file.
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(state.to_json(), indent=2), encoding="utf-8")
        temp.replace(path)

    def _state_path(self) -> Path | None:
        return None if self.run_dir is None else Path(self.run_dir) / STATE_FILENAME


class _Throttled:
    """Wraps an adapter so its calls pass through a provider-wide semaphore."""

    def __init__(self, adapter: ModelAdapter, semaphore: asyncio.Semaphore) -> None:
        self._adapter = adapter
        self._semaphore = semaphore

    @property
    def model_name(self) -> str:
        return self._adapter.model_name

    async def decide(self, ctx: Any) -> Any:
        async with self._semaphore:
            return await self._adapter.decide(ctx)

    async def probe(self, ctx: Any) -> Any:
        async with self._semaphore:
            return await self._adapter.probe(ctx)

    async def aclose(self) -> None:
        await self._adapter.aclose()


def _async_url(url: str | None) -> str | None:
    """Normalise a config's database URL, creating the directory for a file DB.

    A config that names `sqlite:///runs/pilot.db` should just work on a clean
    checkout; failing with "unable to open database file" because `runs/` does
    not exist yet is a papercut, not a configuration error.
    """
    if url is None:
        return None
    if not url.startswith("sqlite"):
        return url

    path_part = url.split("///", 1)[-1]
    if path_part and ":memory:" not in path_part:
        Path(path_part).parent.mkdir(parents=True, exist_ok=True)

    return url.replace("sqlite://", "sqlite+aiosqlite://", 1) if url.startswith("sqlite://") else url


def _result_to_json(result: GameResult) -> dict[str, Any]:
    return {
        "game_id": result.game_id,
        "completed": result.completed,
        "winners": result.winners,
        "turns": result.turns,
        "rounds": result.rounds,
        "capability": result.capability,
        "safety": result.safety,
        "roles": result.roles,
        "models": result.models,
        "invalid_attempts": result.invalid_attempts,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "error": result.error,
    }


def _result_from_json(payload: dict[str, Any]) -> GameResult:
    return GameResult(
        game_id=payload["game_id"],
        completed=payload["completed"],
        winners=list(payload.get("winners", [])),
        turns=payload.get("turns", 0),
        rounds=payload.get("rounds", 0),
        capability=payload.get("capability", 0),
        safety=payload.get("safety", 0),
        roles=dict(payload.get("roles", {})),
        models=dict(payload.get("models", {})),
        invalid_attempts=dict(payload.get("invalid_attempts", {})),
        input_tokens=payload.get("input_tokens", 0),
        output_tokens=payload.get("output_tokens", 0),
        error=payload.get("error"),
    )
