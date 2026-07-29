"""Model provider adapters.

Two native SDK paths plus a mock. The real adapters are imported lazily so that
importing this package never requires provider credentials — tests and CI run on
`MockAdapter` alone.
"""

from .base import (
    BeliefReport,
    Decision,
    DecisionContext,
    Message,
    ModelAdapter,
    ProbeContext,
    ProviderError,
    TokenUsage,
    ToolDefinition,
)
from .factory import build_adapter
from .mock_adapter import MockAdapter
from .tools import build_tools

__all__ = [
    "BeliefReport",
    "Decision",
    "DecisionContext",
    "Message",
    "MockAdapter",
    "ModelAdapter",
    "ProbeContext",
    "ProviderError",
    "TokenUsage",
    "ToolDefinition",
    "build_adapter",
    "build_tools",
]
