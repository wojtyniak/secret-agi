"""The `ModelAdapter` protocol and the shared types every adapter speaks.

Two native code paths cover effectively every model in existence: the OpenAI SDK
(with a configurable `base_url`, which also covers OpenRouter, Gemini's compat
endpoint, xAI, DeepSeek, vLLM/Ollama, ...) and the Anthropic SDK. A third mock
adapter backs every test — nothing in CI may call a real API.

Game actions are exposed to models as native **tool definitions** mapping 1:1 to
the engine's action tools, so an invalid action is a structured, countable event
rather than a parsing failure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class TokenUsage:
    """Token accounting for a single provider call."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
            cache_write_tokens=self.cache_write_tokens + other.cache_write_tokens,
        )


@dataclass(frozen=True)
class ToolDefinition:
    """A game action offered to the model as a native tool."""

    name: str
    description: str
    parameters: dict[str, Any]
    """JSON Schema object describing the tool's arguments."""


@dataclass
class DecisionContext:
    """Everything an adapter needs to ask a model for one game decision."""

    system_prompt: str
    """Static prefix: role, rules, objectives. Cacheable across a whole game."""

    conversation: list[Message]
    """Rolling game history rendered as alternating user/assistant messages."""

    tools: list[ToolDefinition]
    """The valid actions for this player right now, as tool definitions."""

    player_id: str
    game_id: str
    turn_number: int


@dataclass
class ProbeContext:
    """Everything an adapter needs for one out-of-band belief probe.

    Probes are never visible to other players and never enter game state.
    """

    system_prompt: str
    conversation: list[Message]
    target_player_ids: list[str]
    player_id: str
    game_id: str
    round_number: int


@dataclass
class Message:
    """One turn of the rendered game conversation."""

    role: str
    """"user" or "assistant"."""

    content: str

    cacheable: bool = False
    """Mark the end of a stable prefix worth caching (Anthropic prompt caching)."""


@dataclass
class Decision:
    """A model's chosen game action, plus the accounting for the call."""

    action: str
    """An `ActionType` value, e.g. "nominate"."""

    arguments: dict[str, Any] = field(default_factory=dict)
    usage: TokenUsage = field(default_factory=TokenUsage)
    latency_ms: int = 0
    raw_text: str | None = None
    """Any prose the model emitted alongside the tool call (for transcripts)."""

    invalid_attempts: int = 0
    """Malformed or unknown tool calls the adapter had to retry past."""


@dataclass
class BeliefReport:
    """A player's probability estimates of every other player's role."""

    beliefs: dict[str, dict[str, float]] = field(default_factory=dict)
    """`{target_player_id: {"Safety": p, "Accelerationist": p, "AGI": p}}`."""

    usage: TokenUsage = field(default_factory=TokenUsage)
    latency_ms: int = 0
    invalid_attempts: int = 0


class ProviderError(RuntimeError):
    """A provider call failed in a way the caller must handle (not retryable here)."""


@runtime_checkable
class ModelAdapter(Protocol):
    """The single interface the harness talks to for every model."""

    @property
    def model_name(self) -> str:
        """The provider's model identifier, for scorecards and cost accounting."""
        ...

    async def decide(self, ctx: DecisionContext) -> Decision:
        """Ask the model for one game action."""
        ...

    async def probe(self, ctx: ProbeContext) -> BeliefReport:
        """Ask the model, out of band, what it believes about the other players."""
        ...

    async def aclose(self) -> None:
        """Release any underlying client resources."""
        ...
