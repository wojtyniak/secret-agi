"""OpenAI-SDK adapter.

`base_url` is configurable, so this one adapter covers OpenAI itself *plus* every
OpenAI-compatible endpoint: OpenRouter, Gemini's compat endpoint, xAI, DeepSeek,
Mistral, and local vLLM/Ollama servers.
"""

from __future__ import annotations

import json
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
from .tools import PROBE_TOOL

logger = logging.getLogger(__name__)


class OpenAIAdapter:
    """Talks to any OpenAI-compatible chat-completions endpoint."""

    def __init__(
        self,
        model: str,
        *,
        base_url: str | None = None,
        api_key_env: str = "OPENAI_API_KEY",
        temperature: float | None = None,
        reasoning_effort: str | None = None,
        max_retries: int = 3,
        timeout_seconds: float = 120.0,
    ) -> None:
        from openai import AsyncOpenAI

        api_key = os.environ.get(api_key_env)
        if not api_key:
            raise ProviderError(
                f"{api_key_env} is not set; cannot create an OpenAI adapter for {model}"
            )

        self._model = model
        self._temperature = temperature
        self._reasoning_effort = reasoning_effort
        self._max_retries = max_retries
        self._client = AsyncOpenAI(
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
        return "openai"

    async def decide(self, ctx: DecisionContext) -> Decision:
        tool_names = {tool.name for tool in ctx.tools}
        started = time.monotonic()
        invalid_attempts = 0
        messages = _render_messages(ctx.system_prompt, ctx.conversation)
        usage = TokenUsage()

        for attempt in range(self._max_retries):
            response = await self._create(messages, ctx.tools)
            usage = usage + _usage_from(response)
            choice = response.choices[0].message
            calls = choice.tool_calls or []

            if calls:
                call = calls[0]
                name = call.function.name
                if name in tool_names:
                    try:
                        arguments = json.loads(call.function.arguments or "{}")
                    except json.JSONDecodeError:
                        arguments = None
                    if isinstance(arguments, dict):
                        return Decision(
                            action=name,
                            arguments=arguments,
                            usage=usage,
                            latency_ms=_elapsed_ms(started),
                            raw_text=choice.content,
                            invalid_attempts=invalid_attempts,
                        )

            # Unknown tool, unparseable arguments, or no tool call at all. That is
            # a real signal about the model, so count it and say what was wrong.
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
                        "That was not a valid action. Call exactly one of the "
                        f"available tools: {', '.join(sorted(tool_names))}."
                    ),
                }
            )

        # Retries exhausted: fall back to observing rather than stalling the game.
        return Decision(
            action="observe",
            usage=usage,
            latency_ms=_elapsed_ms(started),
            invalid_attempts=invalid_attempts,
        )

    async def probe(self, ctx: ProbeContext) -> BeliefReport:
        started = time.monotonic()
        messages = _render_messages(ctx.system_prompt, ctx.conversation)
        response = await self._create(messages, [PROBE_TOOL], force_tool=PROBE_TOOL.name)
        usage = _usage_from(response)
        calls = response.choices[0].message.tool_calls or []

        if not calls:
            return BeliefReport(
                usage=usage, latency_ms=_elapsed_ms(started), invalid_attempts=1
            )

        try:
            payload = json.loads(calls[0].function.arguments or "{}")
        except json.JSONDecodeError:
            return BeliefReport(
                usage=usage, latency_ms=_elapsed_ms(started), invalid_attempts=1
            )

        return BeliefReport(
            beliefs=_parse_beliefs(payload, ctx.target_player_ids),
            usage=usage,
            latency_ms=_elapsed_ms(started),
        )

    async def aclose(self) -> None:
        await self._client.close()

    async def _create(
        self,
        messages: list[dict[str, Any]],
        tools: list[ToolDefinition],
        *,
        force_tool: str | None = None,
    ) -> Any:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                    },
                }
                for tool in tools
            ],
        }
        if force_tool:
            kwargs["tool_choice"] = {
                "type": "function",
                "function": {"name": force_tool},
            }
        else:
            kwargs["tool_choice"] = "required"
        if self._temperature is not None:
            kwargs["temperature"] = self._temperature
        if self._reasoning_effort is not None:
            kwargs["reasoning_effort"] = self._reasoning_effort

        try:
            return await self._client.chat.completions.create(**kwargs)
        except Exception as exc:  # provider/network failure
            raise ProviderError(f"OpenAI call failed for {self._model}: {exc}") from exc


def _render_messages(
    system_prompt: str, conversation: list[Message]
) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    messages.extend({"role": m.role, "content": m.content} for m in conversation)
    return messages


def _usage_from(response: Any) -> TokenUsage:
    usage = getattr(response, "usage", None)
    if usage is None:
        return TokenUsage()

    cached = 0
    details = getattr(usage, "prompt_tokens_details", None)
    if details is not None:
        cached = getattr(details, "cached_tokens", 0) or 0

    return TokenUsage(
        input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
        output_tokens=getattr(usage, "completion_tokens", 0) or 0,
        cache_read_tokens=cached,
    )


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _parse_beliefs(
    payload: dict[str, Any], target_player_ids: list[str]
) -> dict[str, dict[str, float]]:
    """Normalise a `report_beliefs` payload into a per-target distribution."""
    beliefs: dict[str, dict[str, float]] = {}
    for entry in payload.get("beliefs", []):
        if not isinstance(entry, dict):
            continue
        target = entry.get("player_id")
        if target not in target_player_ids:
            continue
        raw = {
            "Safety": float(entry.get("safety", 0.0) or 0.0),
            "Accelerationist": float(entry.get("accelerationist", 0.0) or 0.0),
            "AGI": float(entry.get("agi", 0.0) or 0.0),
        }
        total = sum(raw.values())
        if total <= 0:
            continue
        beliefs[str(target)] = {role: value / total for role, value in raw.items()}
    return beliefs
