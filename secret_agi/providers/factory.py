"""Build a `ModelAdapter` from run-config values.

Real SDK adapters are imported inside the branch that needs them, so a mock-only
run (all of CI) never imports `openai`/`anthropic` and never needs credentials.
"""

from __future__ import annotations

from typing import Any

from .base import ModelAdapter, ProviderError


def build_adapter(
    provider: str,
    model: str,
    **options: Any,
) -> ModelAdapter:
    """Construct the adapter for `provider`.

    Supported providers: `openai` (any OpenAI-compatible endpoint via `base_url`),
    `anthropic`, and `mock`.
    """
    key = provider.strip().lower()

    if key == "mock":
        from .mock_adapter import MockAdapter

        return MockAdapter(model_name=model, **options)

    if key == "openai":
        from .openai_adapter import OpenAIAdapter

        return OpenAIAdapter(model, **options)

    if key == "anthropic":
        from .anthropic_adapter import AnthropicAdapter

        return AnthropicAdapter(model, **options)

    raise ProviderError(
        f"Unknown provider {provider!r}; expected one of: openai, anthropic, mock"
    )
