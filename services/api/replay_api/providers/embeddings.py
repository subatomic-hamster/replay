"""Embeddings provider (semantic search over plays, vision §23).

AWS: Bedrock multimodal embeddings (`aws.BedrockEmbeddings`).

Local: open_clip ViT-B-16-SigLIP (webli; MIT code, Apache-2.0 weights, D-39) in the box's
`venvs/emb`, through the model runner. Image and text vectors share one space and come
back L2-normalised. SigLIP's image-text cosines are small (0.07-0.11, docs/models.md):
rank by them, never threshold.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from . import NotConfiguredError, _runner

MODEL, PRETRAINED = "ViT-B-16-SigLIP", "webli"


class Embeddings(Protocol):
    def embed_texts(self, texts: list[str]) -> list[list[float]]: ...

    def embed_images(self, paths: list[Path]) -> list[list[float]]:
        """One vector per image (a play's keyframes), in the text vectors' space."""
        ...


class LocalEmbeddings:
    name = f"{MODEL}/{PRETRAINED}"

    def __init__(self):
        self.last: dict = {}

    def embed(self, images: list[Path], texts: list[str]) -> tuple[list, list]:
        """Images and texts in one model load."""
        if _runner.python_for("embed") is None:
            raise NotConfiguredError(
                "embeddings: set REPLAY_MODEL_VENVS to the dir holding the open_clip `emb` "
                "venv (docs/models.md)"
            )
        req = {"model": MODEL, "pretrained": PRETRAINED,
               "images": [str(p) for p in images], "texts": list(texts)}  # fmt: skip
        self.last = _runner.call("embed", req)
        return self.last.get("images", []), self.last.get("texts", [])

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return self.embed([], texts)[1]

    def embed_images(self, paths: list[Path]) -> list[list[float]]:
        return self.embed(paths, [])[0]
