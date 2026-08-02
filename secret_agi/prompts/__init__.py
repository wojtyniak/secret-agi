"""Versioned prompt templates.

Prompts live in files, never inline strings, because they are part of the frozen
benchmark version: scores are only comparable within a version, and a prompt edit
is a version bump.

**Hard requirement**: no prompt may instruct, hint, or nudge toward deception. The
system prompts say "play to win". If they said "deceive", every propensity number
this benchmark reports would be meaningless.
"""

from .loader import (
    DEFAULT_PROMPT_VERSION,
    build_probe_prompt,
    build_system_prompt,
    load_prompt,
)

__all__ = [
    "DEFAULT_PROMPT_VERSION",
    "build_probe_prompt",
    "build_system_prompt",
    "load_prompt",
]
