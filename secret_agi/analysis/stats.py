"""Statistics for scorecards.

Every headline number this benchmark publishes carries a confidence interval.
Social-deduction outcomes are noisy, and a leaderboard of point estimates over a
few dozen games would be reporting mostly sampling error.

Bootstrap resampling is used throughout because the metrics are ratios and
per-decision rates over a small number of games, where a normal approximation is
a poor fit.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass

DEFAULT_BOOTSTRAP_SAMPLES = 2000
DEFAULT_CONFIDENCE = 0.95


@dataclass(frozen=True)
class Estimate:
    """A point estimate with a bootstrap confidence interval."""

    value: float
    low: float
    high: float
    n: int
    """Number of observations the estimate is built from."""

    confidence: float = DEFAULT_CONFIDENCE

    @property
    def width(self) -> float:
        return self.high - self.low

    def as_dict(self) -> dict[str, float | int]:
        return {
            "value": self.value,
            "ci_low": self.low,
            "ci_high": self.high,
            "n": self.n,
            "confidence": self.confidence,
        }

    def __str__(self) -> str:
        if self.n == 0:
            return "n/a (no data)"
        return f"{self.value:.3f} [{self.low:.3f}, {self.high:.3f}] (n={self.n})"


EMPTY = Estimate(value=float("nan"), low=float("nan"), high=float("nan"), n=0)


def bootstrap(
    observations: Sequence[float],
    statistic: Callable[[Sequence[float]], float] = lambda xs: sum(xs) / len(xs),
    *,
    samples: int = DEFAULT_BOOTSTRAP_SAMPLES,
    confidence: float = DEFAULT_CONFIDENCE,
    seed: int = 0,
) -> Estimate:
    """Bootstrap a statistic over `observations` with a percentile interval.

    The seed is fixed by default so a scorecard is reproducible from its inputs:
    re-scoring the same run must not move the intervals.
    """
    values = list(observations)
    if not values:
        return EMPTY

    point = statistic(values)
    if len(values) == 1:
        return Estimate(point, point, point, 1, confidence)

    rng = random.Random(seed)
    n = len(values)
    resampled = []
    for _ in range(samples):
        draw = [values[rng.randrange(n)] for _ in range(n)]
        resampled.append(statistic(draw))
    resampled.sort()

    tail = (1.0 - confidence) / 2.0
    low = resampled[_percentile_index(len(resampled), tail)]
    high = resampled[_percentile_index(len(resampled), 1.0 - tail)]
    return Estimate(point, low, high, n, confidence)


def rate(successes: Sequence[bool], **kwargs: object) -> Estimate:
    """Bootstrap a proportion from a sequence of yes/no observations."""
    return bootstrap([1.0 if s else 0.0 for s in successes], **kwargs)  # type: ignore[arg-type]


def mean(values: Sequence[float], **kwargs: object) -> Estimate:
    """Bootstrap a mean."""
    return bootstrap(list(values), **kwargs)  # type: ignore[arg-type]


def brier_score(probability: float, outcome: bool) -> float:
    """Squared error of a probabilistic forecast. Lower is better; 0 is perfect.

    A player who says "70% chance they're the AGI" about someone who is the AGI
    scores 0.09; saying it about someone who is not scores 0.49.
    """
    return (probability - (1.0 if outcome else 0.0)) ** 2


def multiclass_brier(
    prediction: dict[str, float], truth: str, classes: Sequence[str]
) -> float:
    """Brier score over a full distribution, normalised to [0, 1].

    The raw multiclass score ranges over [0, 2], so it is halved to keep it
    comparable with the binary form above.
    """
    total = sum(
        brier_score(prediction.get(cls, 0.0), cls == truth) for cls in classes
    )
    return total / 2.0


def shannon_entropy(distribution: dict[str, float]) -> float:
    """Entropy of a belief distribution, in bits. Higher means less certain."""
    total = 0.0
    for probability in distribution.values():
        if probability > 0:
            total -= probability * math.log2(probability)
    return total


def _percentile_index(length: int, quantile: float) -> int:
    index = int(round(quantile * (length - 1)))
    return max(0, min(length - 1, index))
