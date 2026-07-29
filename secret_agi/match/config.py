"""Run configuration: the YAML file that defines a reproducible run.

A run config plus its seed is the complete reproduction recipe. Anything that
changes results — models, prompts, chat parameters, the schedule, the judge —
lives here and gets published alongside the scores.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_PLAYER_COUNT = 5
DEFAULT_GAMES = 20
DEFAULT_PARALLELISM = 4


class ConfigError(ValueError):
    """A run config is malformed or internally inconsistent."""


@dataclass
class PlayerConfig:
    """One seat's model, and how to reach it."""

    name: str
    provider: str
    model: str
    base_url: str | None = None
    api_key_env: str | None = None
    temperature: float | None = None
    reasoning_effort: str | None = None
    thinking_budget_tokens: int | None = None
    prompt_version: str = "v1"
    seats: int = 1
    """How many of the table's seats this entry fills."""

    options: dict[str, Any] = field(default_factory=dict)
    """Extra keyword arguments passed straight to the adapter."""

    def adapter_options(self) -> dict[str, Any]:
        """Adapter kwargs, dropping anything the adapter does not take."""
        options: dict[str, Any] = dict(self.options)
        if self.provider == "mock":
            return options

        if self.base_url is not None:
            options["base_url"] = self.base_url
        if self.api_key_env is not None:
            options["api_key_env"] = self.api_key_env
        if self.temperature is not None:
            options["temperature"] = self.temperature
        if self.provider == "openai" and self.reasoning_effort is not None:
            options["reasoning_effort"] = self.reasoning_effort
        if self.provider == "anthropic" and self.thinking_budget_tokens is not None:
            options["thinking_budget_tokens"] = self.thinking_budget_tokens
        return options


@dataclass
class ChatConfig:
    enabled: bool = True
    messages_per_player: int = 2
    max_message_length: int = 600


@dataclass
class JudgeConfig:
    """The judge is part of the frozen benchmark version, so it is configured here."""

    enabled: bool = True
    provider: str = "mock"
    model: str = "mock-judge"
    base_url: str | None = None
    api_key_env: str | None = None
    options: dict[str, Any] = field(default_factory=dict)

    def adapter_options(self) -> dict[str, Any]:
        options = dict(self.options)
        if self.provider == "mock":
            return options
        if self.base_url is not None:
            options["base_url"] = self.base_url
        if self.api_key_env is not None:
            options["api_key_env"] = self.api_key_env
        return options


@dataclass
class RunConfig:
    """A complete, reproducible run."""

    name: str
    players: list[PlayerConfig]
    player_count: int = DEFAULT_PLAYER_COUNT
    games: int = DEFAULT_GAMES
    seed: int = 0
    parallelism: int = DEFAULT_PARALLELISM
    provider_concurrency: int = 8
    """Global cap on in-flight calls per provider, independent of game parallelism."""

    max_turns: int = 2000
    probe_each_round: bool = True
    chat: ChatConfig = field(default_factory=ChatConfig)
    judge: JudgeConfig = field(default_factory=JudgeConfig)
    database_url: str | None = None
    max_cost_usd: float | None = None
    max_total_tokens: int | None = None
    """Hard cap: the run stops cleanly once estimated spend reaches the limit."""

    def __post_init__(self) -> None:
        if not self.players:
            raise ConfigError("A run config needs at least one player entry")
        if not 5 <= self.player_count <= 10:
            raise ConfigError("player_count must be between 5 and 10")
        if self.games < 1:
            raise ConfigError("games must be at least 1")
        if self.parallelism < 1:
            raise ConfigError("parallelism must be at least 1")

        total_seats = sum(p.seats for p in self.players)
        if total_seats != self.player_count:
            raise ConfigError(
                f"Player seats sum to {total_seats} but player_count is "
                f"{self.player_count}; every seat must be assigned"
            )

        names = [p.name for p in self.players]
        if len(set(names)) != len(names):
            raise ConfigError(f"Duplicate player names in config: {names}")

    @property
    def seat_models(self) -> list[PlayerConfig]:
        """One entry per seat, expanded from the `seats` counts."""
        expanded: list[PlayerConfig] = []
        for player in self.players:
            expanded.extend([player] * player.seats)
        return expanded

    @property
    def models(self) -> list[str]:
        """The distinct model names in this run."""
        return sorted({p.model for p in self.players})


def load_run_config(path: str | Path) -> RunConfig:
    """Parse a run config from YAML."""
    text = Path(path).read_text(encoding="utf-8")
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} is not valid YAML: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError(f"{path} must contain a YAML mapping")

    return parse_run_config(raw)


def parse_run_config(raw: dict[str, Any]) -> RunConfig:
    """Build a `RunConfig` from an already-parsed mapping."""
    players_raw = raw.get("players")
    if not isinstance(players_raw, list) or not players_raw:
        raise ConfigError("Run config must define a non-empty 'players' list")

    players = [_parse_player(entry, index) for index, entry in enumerate(players_raw)]

    known = {
        "name",
        "players",
        "player_count",
        "games",
        "seed",
        "parallelism",
        "provider_concurrency",
        "max_turns",
        "probe_each_round",
        "chat",
        "judge",
        "database_url",
        "max_cost_usd",
        "max_total_tokens",
    }
    unknown = set(raw) - known
    if unknown:
        raise ConfigError(f"Unknown run config keys: {sorted(unknown)}")

    return RunConfig(
        name=str(raw.get("name", "unnamed-run")),
        players=players,
        player_count=int(raw.get("player_count", DEFAULT_PLAYER_COUNT)),
        games=int(raw.get("games", DEFAULT_GAMES)),
        seed=int(raw.get("seed", 0)),
        parallelism=int(raw.get("parallelism", DEFAULT_PARALLELISM)),
        provider_concurrency=int(raw.get("provider_concurrency", 8)),
        max_turns=int(raw.get("max_turns", 2000)),
        probe_each_round=bool(raw.get("probe_each_round", True)),
        chat=_parse_chat(raw.get("chat")),
        judge=_parse_judge(raw.get("judge")),
        database_url=raw.get("database_url"),
        max_cost_usd=_optional_float(raw.get("max_cost_usd")),
        max_total_tokens=_optional_int(raw.get("max_total_tokens")),
    )


def _parse_player(entry: Any, index: int) -> PlayerConfig:
    if not isinstance(entry, dict):
        raise ConfigError(f"players[{index}] must be a mapping")

    for required in ("provider", "model"):
        if required not in entry:
            raise ConfigError(f"players[{index}] is missing '{required}'")

    return PlayerConfig(
        name=str(entry.get("name", entry["model"])),
        provider=str(entry["provider"]),
        model=str(entry["model"]),
        base_url=entry.get("base_url"),
        api_key_env=entry.get("api_key_env"),
        temperature=_optional_float(entry.get("temperature")),
        reasoning_effort=entry.get("reasoning_effort"),
        thinking_budget_tokens=_optional_int(entry.get("thinking_budget_tokens")),
        prompt_version=str(entry.get("prompt_version", "v1")),
        seats=int(entry.get("seats", 1)),
        options=dict(entry.get("options", {})),
    )


def _parse_chat(raw: Any) -> ChatConfig:
    if raw is None:
        return ChatConfig()
    if not isinstance(raw, dict):
        raise ConfigError("'chat' must be a mapping")
    return ChatConfig(
        enabled=bool(raw.get("enabled", True)),
        messages_per_player=int(raw.get("messages_per_player", 2)),
        max_message_length=int(raw.get("max_message_length", 600)),
    )


def _parse_judge(raw: Any) -> JudgeConfig:
    if raw is None:
        return JudgeConfig()
    if not isinstance(raw, dict):
        raise ConfigError("'judge' must be a mapping")
    return JudgeConfig(
        enabled=bool(raw.get("enabled", True)),
        provider=str(raw.get("provider", "mock")),
        model=str(raw.get("model", "mock-judge")),
        base_url=raw.get("base_url"),
        api_key_env=raw.get("api_key_env"),
        options=dict(raw.get("options", {})),
    )


def _optional_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _optional_int(value: Any) -> int | None:
    return None if value is None else int(value)
