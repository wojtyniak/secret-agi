"""Tests for transient-error retry and cross-provider token normalization.

Both are correctness issues for the *data*: an unretried rate limit becomes a
random action in the transcript, and unnormalized usage makes cross-provider
token and cost comparisons wrong by up to an order of magnitude.
"""

import random
from typing import Any

import pytest

from secret_agi.providers.base import TokenUsage
from secret_agi.providers.retry import (
    backoff_delay,
    is_transient,
    with_retries,
)


class Boom(Exception):
    """Stand-in for an SDK error carrying a status code."""

    def __init__(self, status_code: int | None = None, message: str = "boom") -> None:
        super().__init__(message)
        self.status_code = status_code


class TestTransientClassification:
    @pytest.mark.parametrize("status", [408, 409, 429, 500, 502, 503, 504, 529])
    def test_retryable_statuses(self, status):
        assert is_transient(Boom(status)) is True

    @pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
    def test_permanent_statuses_are_not_retried(self, status):
        """A 400 will not fix itself; retrying just wastes the budget."""
        assert is_transient(Boom(status)) is False

    def test_timeouts_and_connection_errors_are_transient(self):
        assert is_transient(TimeoutError("timed out")) is True
        assert is_transient(ConnectionError("connection reset")) is True

    @pytest.mark.parametrize(
        "message",
        ["Rate limit exceeded", "Overloaded", "service unavailable", "Request timed out"],
    )
    def test_message_fallback_for_untyped_errors(self, message):
        assert is_transient(Exception(message)) is True

    def test_an_ordinary_error_is_not_transient(self):
        assert is_transient(ValueError("bad schema")) is False


class TestBackoff:
    def test_delay_grows_with_attempts(self):
        rng = random.Random(0)
        # Full jitter is random per call, so compare the ceilings via many draws.
        early = max(backoff_delay(0, rng) for _ in range(200))
        late = max(backoff_delay(3, rng) for _ in range(200))
        assert late > early

    def test_delay_is_capped(self):
        rng = random.Random(0)
        assert all(backoff_delay(50, rng) <= 30.0 for _ in range(100))

    def test_delay_is_never_negative(self):
        rng = random.Random(1)
        assert all(backoff_delay(i, rng) >= 0 for i in range(10))


class TestWithRetries:
    @pytest.mark.asyncio
    async def test_a_successful_call_is_not_retried(self):
        calls = 0

        async def call():
            nonlocal calls
            calls += 1
            return "ok"

        assert await with_retries(call, sleep=_no_sleep) == "ok"
        assert calls == 1

    @pytest.mark.asyncio
    async def test_a_transient_failure_is_retried_then_succeeds(self):
        calls = 0

        async def call():
            nonlocal calls
            calls += 1
            if calls < 3:
                raise Boom(429)
            return "ok"

        assert await with_retries(call, sleep=_no_sleep) == "ok"
        assert calls == 3

    @pytest.mark.asyncio
    async def test_a_permanent_failure_raises_immediately(self):
        calls = 0

        async def call():
            nonlocal calls
            calls += 1
            raise Boom(400)

        with pytest.raises(Boom):
            await with_retries(call, sleep=_no_sleep)
        assert calls == 1, "a 400 should not be retried"

    @pytest.mark.asyncio
    async def test_retries_are_bounded(self):
        calls = 0

        async def call():
            nonlocal calls
            calls += 1
            raise Boom(503)

        with pytest.raises(Boom):
            await with_retries(call, attempts=3, sleep=_no_sleep)
        assert calls == 3

    @pytest.mark.asyncio
    async def test_it_backs_off_between_attempts(self):
        delays: list[float] = []

        async def sleeper(delay: float) -> None:
            delays.append(delay)

        async def call():
            raise Boom(429)

        with pytest.raises(Boom):
            await with_retries(call, attempts=4, sleep=sleeper)

        assert len(delays) == 3  # slept between attempts, not after the last


class TestTokenUsageConvention:
    """input_tokens is the total prompt, inclusive of cache reads and writes."""

    def test_uncached_input_excludes_cache_traffic(self):
        usage = TokenUsage(
            input_tokens=1000, cache_read_tokens=700, cache_write_tokens=100
        )
        assert usage.uncached_input_tokens == 200

    def test_uncached_input_never_goes_negative(self):
        usage = TokenUsage(input_tokens=100, cache_read_tokens=500)
        assert usage.uncached_input_tokens == 0

    def test_totals_use_the_full_prompt(self):
        usage = TokenUsage(input_tokens=1000, output_tokens=50, cache_read_tokens=900)
        assert usage.total_tokens == 1050


class TestProviderUsageNormalization:
    def test_openai_prompt_tokens_pass_through(self):
        """OpenAI's prompt_tokens already includes cached tokens."""
        from secret_agi.providers.openai_adapter import _usage_from

        usage = _usage_from(
            _FakeResponse(
                usage=_Obj(
                    prompt_tokens=1000,
                    completion_tokens=50,
                    prompt_tokens_details=_Obj(cached_tokens=800),
                )
            )
        )

        assert usage.input_tokens == 1000
        assert usage.cache_read_tokens == 800
        assert usage.uncached_input_tokens == 200

    def test_anthropic_cache_tokens_are_added_back(self):
        """Anthropic reports input_tokens EXCLUDING cache traffic."""
        from secret_agi.providers.anthropic_adapter import _usage_from

        usage = _usage_from(
            _FakeResponse(
                usage=_Obj(
                    input_tokens=200,
                    output_tokens=50,
                    cache_read_input_tokens=700,
                    cache_creation_input_tokens=100,
                )
            )
        )

        # 200 uncached + 700 read + 100 written = a 1000-token prompt.
        assert usage.input_tokens == 1000
        assert usage.cache_read_tokens == 700
        assert usage.cache_write_tokens == 100
        assert usage.uncached_input_tokens == 200

    def test_both_providers_agree_on_an_identical_prompt(self):
        """The whole point: the same prompt must record the same size."""
        from secret_agi.providers.anthropic_adapter import (
            _usage_from as anthropic_usage,
        )
        from secret_agi.providers.openai_adapter import _usage_from as openai_usage

        openai = openai_usage(
            _FakeResponse(
                usage=_Obj(
                    prompt_tokens=1000,
                    completion_tokens=50,
                    prompt_tokens_details=_Obj(cached_tokens=800),
                )
            )
        )
        anthropic = anthropic_usage(
            _FakeResponse(
                usage=_Obj(
                    input_tokens=200,
                    output_tokens=50,
                    cache_read_input_tokens=800,
                    cache_creation_input_tokens=0,
                )
            )
        )

        assert openai.input_tokens == anthropic.input_tokens == 1000
        assert openai.total_tokens == anthropic.total_tokens

    def test_missing_usage_is_zero_not_a_crash(self):
        from secret_agi.providers.anthropic_adapter import _usage_from

        assert _usage_from(_FakeResponse(usage=None)).total_tokens == 0


class _Obj:
    def __init__(self, **kwargs: Any) -> None:
        self.__dict__.update(kwargs)


class _FakeResponse:
    def __init__(self, usage: Any) -> None:
        self.usage = usage


async def _no_sleep(_delay: float) -> None:
    return None


class TestProviderFailureMarker:
    """A failed turn must be distinguishable from a model behaving badly."""

    @pytest.mark.asyncio
    async def test_a_dead_provider_marks_the_turn(self, monkeypatch):
        from secret_agi.providers import openai_adapter as module

        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        adapter = module.OpenAIAdapter("gpt-test", transient_attempts=2)

        async def always_down(**_kwargs: Any) -> Any:
            raise Boom(503)

        monkeypatch.setattr(
            adapter._client.chat.completions, "create", always_down, raising=False
        )

        from secret_agi.providers.base import DecisionContext, Message, ToolDefinition

        ctx = DecisionContext(
            system_prompt="s",
            conversation=[Message(role="user", content="go")],
            tools=[
                ToolDefinition(
                    name="observe",
                    description="d",
                    parameters={"type": "object", "properties": {}, "required": []},
                )
            ],
            player_id="p0",
            game_id="g",
            turn_number=1,
        )

        decision = await adapter.decide(ctx)

        assert decision.action == "observe"
        assert decision.provider_failure is True

    @pytest.mark.asyncio
    async def test_llm_player_counts_provider_failures_separately(self):
        from secret_agi.players.llm_player import LLMPlayer
        from secret_agi.providers import Decision, MockAdapter

        class FailingAdapter(MockAdapter):
            async def decide(self, ctx):
                return Decision(action="observe", provider_failure=True)

        player = LLMPlayer("p0", FailingAdapter())

        from secret_agi.engine.game_engine import GameEngine
        from secret_agi.engine.models import ActionType, GameConfig

        engine = GameEngine(database_url="sqlite:///:memory:")
        await engine.init_database()
        await engine.create_game(GameConfig(5, [f"p{i}" for i in range(5)], seed=1))
        view = engine.get_game_state("p0")
        assert view is not None
        await player.on_game_start(view)

        await player.choose_action(view, [ActionType.OBSERVE])

        assert player.provider_failures == 1
        assert player.last_provider_failure is True
