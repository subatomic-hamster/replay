"""Embeddings provider (semantic search over plays, vision §23).

AWS: Bedrock multimodal embeddings (`aws.BedrockEmbeddings`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from . import NotConfiguredError


class Embeddings(Protocol):
    def embed_texts(self, texts: list[str]) -> list[list[float]]: ...

    def embed_images(self, paths: list[Path]) -> list[list[float]]:
        """One vector per image (a play's keyframes), in the text vectors' space."""
        ...


class LocalEmbeddings:
    """Placeholder until a local embedding model is chosen (see docs/models.md)."""

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        raise NotConfiguredError("embeddings: no local model configured yet (see docs/models.md)")

    def embed_images(self, paths: list[Path]) -> list[list[float]]:
        raise NotConfiguredError("embeddings: no local model configured yet (see docs/models.md)")
