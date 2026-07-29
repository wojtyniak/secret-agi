"""Retry for transient provider failures.

A rate-limit blip must not become behavioural data. Without this, a single 429
during a nomination turn raises `ProviderError`, `LLMPlayer` converts it to a
forced OBSERVE, and the runner substitutes a *random* action — so the transcript
records the model nominating a random engineer, indistinguishable from the model
actually choosing to.

Transient failures are retried with exponential backoff. Only once retries are
exhausted does the fallback chain engage, and the resulting decision is marked
`provider_failure` so analysis can exclude the turn rather than score it.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_ATTEMPTS = 4
BASE_DELAY_SECONDS = 0.5
MAX_DELAY_SECONDS = 30.0

# Status codes worth retrying: rate limits, server faults, and gateway hiccups.
_RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504, 529}

_RETRYABLE_MARKERS = (
    "rate limit",
    "rate_limit",
    "timeout",
    "timed out",
    "overloaded",
    "temporarily unavailable",
    "service unavailable",
    "bad gateway",
    "connection reset",
    "connection error",
    "remote end closed",
)


def is_transient(exc: BaseException) -> bool:
    """Whether an exception looks like a temporary provider problem.

    Checked structurally where the SDKs expose a status code, and by message
    otherwise — the two SDKs raise different exception hierarchies and we do not
    want to import either one here.
    """
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    if isinstance(status, int):
        return status in _RETRYABLE_STATUS

    if isinstance(exc, TimeoutError | ConnectionError):
        return True

    message = str(exc).lower()
    return any(marker in message for marker in _RETRYABLE_MARKERS)


def backoff_delay(attempt: int, rng: random.Random | None = None) -> float:
    """Exponential backoff with jitter, for attempt 0, 1, 2, ..."""
    chooser = rng or random
    ceiling = min(MAX_DELAY_SECONDS, BASE_DELAY_SECONDS * (2**attempt))
    # Full jitter: spreads retries so concurrent games do not stampede together.
    return chooser.uniform(0.0, ceiling)


async def with_retries[T](
    call: Callable[[], Awaitable[T]],
    *,
    attempts: int = DEFAULT_ATTEMPTS,
    label: str = "provider call",
    sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    rng: random.Random | None = None,
) -> T:
    """Run `call`, retrying transient failures with exponential backoff.

    Re-raises the last exception once attempts are exhausted, and re-raises a
    non-transient failure immediately — a 400 will not fix itself.
    """
    last: BaseException | None = None

    for attempt in range(attempts):
        try:
            return await call()
        except Exception as exc:
            last = exc
            if not is_transient(exc) or attempt == attempts - 1:
                raise
            delay = backoff_delay(attempt, rng)
            logger.warning(
                "%s failed with a transient error (attempt %d/%d), retrying in %.1fs: %s",
                label,
                attempt + 1,
                attempts,
                delay,
                exc,
            )
            await sleep(delay)

    # Unreachable: the loop either returns or raises.
    raise last if last else RuntimeError(f"{label} failed without an exception")
