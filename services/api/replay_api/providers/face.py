"""Face provider: opt-in enrollment only (vision §21). Never matches unenrolled people:
`identify` may only return profiles that called `enroll`. AWS: Rekognition collections
(`aws.RekognitionFace`)."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from . import NotConfiguredError


class Face(Protocol):
    def enroll(self, profile_id: str, images: list[Path]) -> dict: ...

    def identify(self, image: Path, *, min_similarity: float = 0.8) -> list[dict]:
        """`[{profile_id, similarity, box}]` over enrolled profiles only."""
        ...

    def forget(self, profile_id: str) -> None: ...


class LocalFace:
    """Placeholder until a local face model with a usable license is chosen
    (docs/licenses.md)."""

    def enroll(self, profile_id: str, images: list[Path]) -> dict:
        raise NotConfiguredError("face: no local face model configured yet (docs/licenses.md)")

    def identify(self, image: Path, *, min_similarity: float = 0.8) -> list[dict]:
        raise NotConfiguredError("face: no local face model configured yet (docs/licenses.md)")

    def forget(self, profile_id: str) -> None:
        raise NotConfiguredError("face: no local face model configured yet (docs/licenses.md)")
