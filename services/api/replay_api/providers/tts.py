"""Text-to-speech provider (commentary audio, vision §9). AWS: Polly (`aws.PollyTTS`)."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from . import NotConfiguredError


class TTS(Protocol):
    def synthesize(self, text: str, out_path: Path, *, voice: str | None = None) -> Path:
        """Speak `text` into a WAV at `out_path`; return the path."""
        ...


class LocalTTS:
    """Placeholder until a local TTS model is chosen (see docs/models.md)."""

    def synthesize(self, text: str, out_path: Path, *, voice: str | None = None) -> Path:
        raise NotConfiguredError("tts: no local TTS model configured yet (see docs/models.md)")
