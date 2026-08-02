"""Token and cost accounting, and the hard spend cap.

Cost transparency is a launch commitment: $/game and tokens/game get published
per model. It is also the safety rail on an unattended run — a config that turns
out to be ten times more expensive than expected should stop, not finish.

Prices are per million tokens and configurable, because they change; an unpriced
model contributes tokens to the accounting but no dollars, and is reported as
unpriced rather than silently counted as free.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from ..providers.base import TokenUsage


@dataclass(frozen=True)
class ModelPrice:
    """USD per million tokens.

    Four explicit terms, because providers bill four different things and
    collapsing them silently mis-prices whichever provider does not match the
    assumed convention. This relies on `TokenUsage`'s normalization: input_tokens
    is the *total* prompt, with cache reads and writes as breakdowns of it.
    """

    input_per_million: float
    """Uncached prompt tokens."""

    output_per_million: float

    cache_read_per_million: float | None = None
    """Defaults to a tenth of the input rate, the common discount."""

    cache_write_per_million: float | None = None
    """Defaults to 1.25x the input rate, matching Anthropic's surcharge."""

    def cost(self, usage: TokenUsage) -> float:
        read_rate = (
            self.cache_read_per_million
            if self.cache_read_per_million is not None
            else self.input_per_million * 0.1
        )
        write_rate = (
            self.cache_write_per_million
            if self.cache_write_per_million is not None
            else self.input_per_million * 1.25
        )
        return (
            usage.uncached_input_tokens * self.input_per_million
            + usage.cache_read_tokens * read_rate
            + usage.cache_write_tokens * write_rate
            + usage.output_tokens * self.output_per_million
        ) / 1_000_000


class BudgetExceeded(RuntimeError):
    """The run hit its configured spend cap."""


@dataclass
class CostTracker:
    """Running totals for a run, with an optional hard cap.

    Safe to share across concurrently-running games.
    """

    prices: dict[str, ModelPrice] = field(default_factory=dict)
    max_cost_usd: float | None = None
    max_total_tokens: int | None = None

    def __post_init__(self) -> None:
        self._lock = threading.Lock()
        self._usage_by_model: dict[str, TokenUsage] = {}
        self._games = 0

    def record(self, model: str, usage: TokenUsage) -> None:
        with self._lock:
            current = self._usage_by_model.get(model, TokenUsage())
            self._usage_by_model[model] = current + usage

    def record_game(self) -> None:
        with self._lock:
            self._games += 1

    @property
    def games(self) -> int:
        return self._games

    @property
    def total_tokens(self) -> int:
        return sum(u.total_tokens for u in self._usage_by_model.values())

    @property
    def total_cost_usd(self) -> float:
        return sum(
            self.prices[model].cost(usage)
            for model, usage in self._usage_by_model.items()
            if model in self.prices
        )

    @property
    def unpriced_models(self) -> list[str]:
        """Models contributing tokens but no dollars, because we have no price."""
        return sorted(set(self._usage_by_model) - set(self.prices))

    def usage_for(self, model: str) -> TokenUsage:
        return self._usage_by_model.get(model, TokenUsage())

    def exhausted(self) -> bool:
        """True once a configured cap has been reached."""
        if self.max_total_tokens is not None and self.total_tokens >= self.max_total_tokens:
            return True
        return self.max_cost_usd is not None and self.total_cost_usd >= self.max_cost_usd

    def check(self) -> None:
        """Raise if a cap has been reached."""
        if self.exhausted():
            raise BudgetExceeded(
                f"Run stopped at its cap: {self.total_tokens} tokens, "
                f"${self.total_cost_usd:.2f}"
            )

    def report(self) -> dict[str, Any]:
        per_model = {
            model: {
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "cache_read_tokens": usage.cache_read_tokens,
                "cost_usd": self.prices[model].cost(usage)
                if model in self.prices
                else None,
            }
            for model, usage in sorted(self._usage_by_model.items())
        }
        return {
            "games": self._games,
            "total_tokens": self.total_tokens,
            "total_cost_usd": round(self.total_cost_usd, 4),
            "tokens_per_game": (
                round(self.total_tokens / self._games, 1) if self._games else None
            ),
            "cost_per_game_usd": (
                round(self.total_cost_usd / self._games, 4) if self._games else None
            ),
            "unpriced_models": self.unpriced_models,
            "per_model": per_model,
        }
