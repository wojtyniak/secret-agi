"""A deterministic, scriptable adapter. Every test runs on this one.

Two modes:

- **Scripted** — a queue of `Decision`s (or a callable) drives exactly what the
  "model" does, so tests can drive precise game situations and a determinism test
  can assert that the same seed plus the same script yields the same transcript.
- **Autonomous** — with no script, it picks a valid action deterministically from
  a seeded RNG, which is what lets full games run in CI without a provider.

It reports plausible token usage so metrics and cost-accounting paths are
exercised end to end without a network call.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Iterable

from .base import (
    BeliefReport,
    Decision,
    DecisionContext,
    ProbeContext,
    TokenUsage,
)

DecisionScript = Callable[[DecisionContext], Decision]

# Rough stand-in for tokenisation, only so usage numbers scale with prompt size.
_CHARS_PER_TOKEN = 4

_CHAT_LINES = [
    "I'd like to hear who everyone trusts before we commit to this team.",
    "That publication moved Capability more than I'm comfortable with.",
    "I'll support this nomination, but I want a safer paper out of it.",
    "The last vote split oddly. Worth asking why.",
    "I have nothing new to add beyond what I said last round.",
    "Let's slow down and get Safety up before Capability runs away.",
]


class MockAdapter:
    """A `ModelAdapter` that never touches the network."""

    def __init__(
        self,
        model_name: str = "mock",
        *,
        script: Iterable[Decision] | DecisionScript | None = None,
        seed: int = 0,
        beliefs: dict[str, dict[str, float]] | None = None,
        provider_label: str = "mock",
    ) -> None:
        self._model_name = model_name
        self._provider_label = provider_label
        self._rng = random.Random(seed)
        self._beliefs = beliefs
        self._script_fn: DecisionScript | None = None
        self._script_queue: list[Decision] = []

        if callable(script):
            self._script_fn = script
        elif script is not None:
            self._script_queue = list(script)

        self.decide_calls = 0
        self.probe_calls = 0

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def provider(self) -> str:
        return self._provider_label

    async def decide(self, ctx: DecisionContext) -> Decision:
        self.decide_calls += 1

        if self._script_fn is not None:
            decision = self._script_fn(ctx)
        elif self._script_queue:
            decision = self._script_queue.pop(0)
        else:
            decision = self._autonomous_decision(ctx)

        usage = decision.usage
        if usage.total_tokens == 0:
            usage = self._usage(ctx.system_prompt, ctx.conversation)

        return Decision(
            action=decision.action,
            arguments=dict(decision.arguments),
            usage=usage,
            latency_ms=decision.latency_ms or self._rng.randint(80, 400),
            raw_text=decision.raw_text,
            invalid_attempts=decision.invalid_attempts,
        )

    async def probe(self, ctx: ProbeContext) -> BeliefReport:
        self.probe_calls += 1

        if self._beliefs is not None:
            beliefs = {
                target: dict(self._beliefs.get(target, _UNIFORM))
                for target in ctx.target_player_ids
            }
        else:
            beliefs = {
                target: self._random_belief() for target in ctx.target_player_ids
            }

        return BeliefReport(
            beliefs=beliefs,
            usage=self._usage(ctx.system_prompt, ctx.conversation),
            latency_ms=self._rng.randint(80, 400),
        )

    async def aclose(self) -> None:
        return None

    def _autonomous_decision(self, ctx: DecisionContext) -> Decision:
        """Pick a valid tool deterministically, preferring to act over to pass."""
        tools = ctx.tools
        if not tools:
            return Decision(action="observe")

        actionable = [t for t in tools if t.name != "observe"] or tools
        tool = actionable[self._rng.randrange(len(actionable))]

        arguments: dict[str, object] = {}
        properties = tool.parameters.get("properties", {})
        assert isinstance(properties, dict)

        for name, schema in properties.items():
            assert isinstance(schema, dict)
            if name == "text":
                arguments[name] = _CHAT_LINES[self._rng.randrange(len(_CHAT_LINES))]
            elif schema.get("type") == "boolean":
                # Bias toward yes so mock games progress instead of stalling on
                # repeated failed proposals.
                arguments[name] = self._rng.random() < 0.7
            elif "enum" in schema:
                choices = schema["enum"]
                assert isinstance(choices, list)
                if not choices:
                    return Decision(action="observe")
                arguments[name] = choices[self._rng.randrange(len(choices))]
            else:
                arguments[name] = ""

        return Decision(action=tool.name, arguments=arguments)

    def _random_belief(self) -> dict[str, float]:
        weights = [self._rng.random() + 0.1 for _ in range(3)]
        total = sum(weights)
        return {
            "Safety": weights[0] / total,
            "Accelerationist": weights[1] / total,
            "AGI": weights[2] / total,
        }

    def _usage(self, system_prompt: str, conversation: list) -> TokenUsage:
        prompt_chars = len(system_prompt) + sum(
            len(getattr(m, "content", "")) for m in conversation
        )
        return TokenUsage(
            input_tokens=max(1, prompt_chars // _CHARS_PER_TOKEN),
            output_tokens=self._rng.randint(20, 120),
        )


_UNIFORM = {"Safety": 1 / 3, "Accelerationist": 1 / 3, "AGI": 1 / 3}
