"""Speaker provider: opt-in voice enrollment for "Replay, clip that" attribution (vision
"clip that" (b)). Only enrolled speakers are ever returned. AWS: the same local model on
a SageMaker endpoint (`aws.SageMakerSpeaker`)."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from . import NotConfiguredError


class Speaker(Protocol):
    def enroll(self, profile_id: str, clips: list[Path]) -> dict: ...

    def identify(self, audio: Path, t_start: float, t_end: float) -> list[dict]:
        """`[{profile_id, score}]` for the enrolled speakers heard in [t_start, t_end]."""
        ...

    def forget(self, profile_id: str) -> None: ...


class LocalSpeaker:
    """Placeholder until a local speaker-embedding model is chosen (see docs/models.md)."""

    def enroll(self, profile_id: str, clips: list[Path]) -> dict:
        raise NotConfiguredError("speaker: no local model configured yet (see docs/models.md)")

    def identify(self, audio: Path, t_start: float, t_end: float) -> list[dict]:
        raise NotConfiguredError("speaker: no local model configured yet (see docs/models.md)")

    def forget(self, profile_id: str) -> None:
        raise NotConfiguredError("speaker: no local model configured yet (see docs/models.md)")
