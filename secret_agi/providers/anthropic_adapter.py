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
from .tools import PROBE_TOOL

logger = logging.getLogger(__name__)

_DEFAULT_MAX_TOKENS = 2048


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
    ) -> None:
        from anthropic import AsyncAnthropic

        api_key = os.environ.get(api_key_env)
        if not api_key:
            raise ProviderError(
                f"{api_key_env} is not set; cannot create an Anthropic adapter for {model}"
            )

        self._model = model
        self._temperature = temperature
        self._thinking_budget_tokens = thinking_budget_tokens
        self._max_tokens = max_tokens
        self._max_retries = max_retries
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
            response = await self._create(ctx.system_prompt, messages, ctx.tools)
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
        response = await self._create(
            ctx.system_prompt, messages, [PROBE_TOOL], force_tool=PROBE_TOOL.name
        )
        usage = _usage_from(response)
        tool_use, _ = _split_content(response)

        if tool_use is None or not isinstance(tool_use.input, dict):
            return BeliefReport(
                usage=usage, latency_ms=_elapsed_ms(started), invalid_attempts=1
            )

        return BeliefReport(
            beliefs=_parse_beliefs(dict(tool_use.input), ctx.target_player_ids),
            usage=usage,
            latency_ms=_elapsed_ms(started),
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

        try:
            return await self._client.messages.create(**kwargs)
        except Exception as exc:  # provider/network failure
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
    return TokenUsage(
        input_tokens=getattr(usage, "input_tokens", 0) or 0,
        output_tokens=getattr(usage, "output_tokens", 0) or 0,
        cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
        cache_write_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
    )


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
