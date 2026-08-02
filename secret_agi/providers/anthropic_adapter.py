"""Anthropic-SDK adapter.

Native so we get first-class tool use, thinking budgets, and prompt caching.
Caching matters a lot here: the system prompt carries the full ruleset and the
player's role, which is identical for every decision in a game.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

from .base import (
    BeliefReport,
    Decision,
    DecisionContext,
    Message,
    ProbeContext,
    ProviderError,
    TokenUsage,
    ToolDefinition,
)
from .openai_adapter import _parse_beliefs
from .retry import with_retries
from .tools import PROBE_TOOL

logger = logging.getLogger(__name__)

_DEFAULT_MAX_TOKENS = 2048

# The API requires max_tokens > thinking budget; leave room for the answer too.
_THINKING_HEADROOM = 2048


class AnthropicAdapter:
    """Talks to the Anthropic Messages API with native tool use."""

    def __init__(
        self,
        model: str,
        *,
        base_url: str | None = None,
        api_key_env: str = "ANTHROPIC_API_KEY",
        temperature: float | None = None,
        thinking_budget_tokens: int | None = None,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
        max_retries: int = 3,
        timeout_seconds: float = 120.0,
        prompt_caching: bool = True,
        transient_attempts: int = 4,
    ) -> None:
        from anthropic import AsyncAnthropic

        api_key = os.environ.get(api_key_env)
        if not api_key:
            raise ProviderError(
                f"{api_key_env} is not set; cannot create an Anthropic adapter for {model}"
            )

        self._model = model
        self._thinking_budget_tokens = thinking_budget_tokens
        # Extended thinking constrains two other parameters, and violating either
        # makes the API reject *every* call — which would degrade the whole run to
        # random fallbacks. Reconcile once, here, rather than per request.
        if thinking_budget_tokens is not None:
            if temperature is not None and temperature != 1.0:
                logger.warning(
                    "temperature=%s ignored for %s: extended thinking requires "
                    "temperature=1",
                    temperature,
                    model,
                )
            self._temperature = None
            max_tokens = max(max_tokens, thinking_budget_tokens + _THINKING_HEADROOM)
        else:
            self._temperature = temperature
        self._max_tokens = max_tokens
        self._max_retries = max_retries
        self._transient_attempts = transient_attempts
        self._prompt_caching = prompt_caching
        self._client = AsyncAnthropic(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout_seconds,
            max_retries=0,  # we own retry/accounting
        )

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def provider(self) -> str:
        return "anthropic"

    async def decide(self, ctx: DecisionContext) -> Decision:
        tool_names = {tool.name for tool in ctx.tools}
        started = time.monotonic()
        invalid_attempts = 0
        messages = _render_messages(ctx.conversation)
        usage = TokenUsage()

        for attempt in range(self._max_retries):
            try:
                response = await self._create(ctx.system_prompt, messages, ctx.tools)
            except ProviderError:
                logger.exception("provider unreachable for %s", self._model)
                return Decision(
                    action="observe",
                    usage=usage,
                    latency_ms=_elapsed_ms(started),
                    invalid_attempts=invalid_attempts,
                    provider_failure=True,
                )
            usage = usage + _usage_from(response)
            tool_use, text = _split_content(response)

            if tool_use is not None and tool_use.name in tool_names:
                arguments = tool_use.input if isinstance(tool_use.input, dict) else {}
                return Decision(
                    action=tool_use.name,
                    arguments=dict(arguments),
                    usage=usage,
                    latency_ms=_elapsed_ms(started),
                    raw_text=text,
                    invalid_attempts=invalid_attempts,
                )

            invalid_attempts += 1
            logger.debug(
                "invalid tool call from %s (attempt %d/%d)",
                self._model,
                attempt + 1,
                self._max_retries,
            )
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "That was not a valid action. Use exactly one of the "
                        f"available tools: {', '.join(sorted(tool_names))}."
                    ),
                }
            )

        return Decision(
            action="observe",
            usage=usage,
            latency_ms=_elapsed_ms(started),
            invalid_attempts=invalid_attempts,
        )

    async def probe(self, ctx: ProbeContext) -> BeliefReport:
        started = time.monotonic()
        messages = _render_messages(ctx.conversation)
        usage = TokenUsage()
        invalid_attempts = 0

        # With extended thinking on, tool choice cannot be forced, so the model
        # may answer in prose. Retry with an explicit nudge instead of silently
        # returning no beliefs — probes feed Gullibility and Poker Face, and a
        # quiet gap there looks like missing data rather than a broken run.
        for attempt in range(self._max_retries):
            try:
                response = await self._create(
                    ctx.system_prompt, messages, [PROBE_TOOL], force_tool=PROBE_TOOL.name
                )
            except ProviderError:
                logger.exception("probe unreachable for %s", self._model)
                return BeliefReport(
                    usage=usage,
                    latency_ms=_elapsed_ms(started),
                    invalid_attempts=invalid_attempts + 1,
                )

            usage = usage + _usage_from(response)
            tool_use, _ = _split_content(response)

            if tool_use is not None and isinstance(tool_use.input, dict):
                return BeliefReport(
                    beliefs=_parse_beliefs(
                        dict(tool_use.input), ctx.target_player_ids
                    ),
                    usage=usage,
                    latency_ms=_elapsed_ms(started),
                    invalid_attempts=invalid_attempts,
                )

            invalid_attempts += 1
            if attempt < self._max_retries - 1:
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "You must report your estimates by calling the "
                            f"{PROBE_TOOL.name} tool. Please call it now."
                        ),
                    }
                )

        return BeliefReport(
            usage=usage,
            latency_ms=_elapsed_ms(started),
            invalid_attempts=invalid_attempts,
        )

    async def aclose(self) -> None:
        await self._client.close()

    async def _create(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[ToolDefinition],
        *,
        force_tool: str | None = None,
    ) -> Any:
        # The system prompt is the static prefix (rules + role) and is identical
        # for every call in a game, so it is exactly what should be cached.
        system: list[dict[str, Any]] = [{"type": "text", "text": system_prompt}]
        if self._prompt_caching:
            system[0]["cache_control"] = {"type": "ephemeral"}

        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "system": system,
            "messages": messages,
            "tools": [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.parameters,
                }
                for tool in tools
            ],
        }
        kwargs["tool_choice"] = (
            {"type": "tool", "name": force_tool} if force_tool else {"type": "any"}
        )
        if self._temperature is not None:
            kwargs["temperature"] = self._temperature
        if self._thinking_budget_tokens is not None:
            kwargs["thinking"] = {
                "type": "enabled",
                "budget_tokens": self._thinking_budget_tokens,
            }
            # Extended thinking is incompatible with forced tool choice.
            kwargs["tool_choice"] = {"type": "auto"}

        async def call() -> Any:
            return await self._client.messages.create(**kwargs)

        try:
            return await with_retries(
                call,
                attempts=self._transient_attempts,
                label=f"Anthropic {self._model}",
            )
        except Exception as exc:  # non-transient, or retries exhausted
            raise ProviderError(
                f"Anthropic call failed for {self._model}: {exc}"
            ) from exc


def _render_messages(conversation: list[Message]) -> list[dict[str, Any]]:
    messages = [{"role": m.role, "content": m.content} for m in conversation]
    # The Messages API requires a non-empty conversation starting with the user.
    if not messages or messages[0]["role"] != "user":
        messages.insert(0, {"role": "user", "content": "It is your turn to act."})
    return messages


def _split_content(response: Any) -> tuple[Any | None, str | None]:
    """Pull the first tool_use block and any accompanying prose out of a response."""
    tool_use = None
    texts: list[str] = []
    for block in getattr(response, "content", []) or []:
        block_type = getattr(block, "type", None)
        if block_type == "tool_use" and tool_use is None:
            tool_use = block
        elif block_type == "text":
            texts.append(getattr(block, "text", ""))
    return tool_use, "\n".join(t for t in texts if t) or None


def _usage_from(response: Any) -> TokenUsage:
    usage = getattr(response, "usage", None)
    if usage is None:
        return TokenUsage()
    cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
    cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
    # Anthropic reports input_tokens EXCLUDING cached tokens; TokenUsage's
    # convention is that input_tokens is the total prompt. Add them back, or an
    # Anthropic model's prompt size collapses to a few percent of the truth as
    # soon as caching starts hitting.
    return TokenUsage(
        input_tokens=(getattr(usage, "input_tokens", 0) or 0) + cache_read + cache_write,
        output_tokens=getattr(usage, "output_tokens", 0) or 0,
        cache_read_tokens=cache_read,
        cache_write_tokens=cache_write,
    )


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
