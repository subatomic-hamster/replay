"""LLM provider (commentary scripts, advice, card titles, free-text → structured filter).

Grounding rule (vision): callers hand it structured JSON and accept only structured
output; it never invents timestamps. AWS: Bedrock Converse / Nova (`aws.BedrockLLM`).
"""

from __future__ import annotations

from typing import Protocol

from . import NotConfiguredError


class LLM(Protocol):
    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        json_schema: dict | None = None,
        max_tokens: int = 512,
    ) -> str:
        """Return the model's text; with `json_schema`, a JSON document matching it."""
        ...


class LocalLLM:
    """Placeholder until a local LLM runtime is chosen (see docs/models.md)."""

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        json_schema: dict | None = None,
        max_tokens: int = 512,
    ) -> str:
        raise NotConfiguredError("llm: no local LLM configured yet (see docs/models.md)")
