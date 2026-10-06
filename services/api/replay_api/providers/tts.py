"""Text-to-speech provider (commentary audio, vision §9). AWS: Polly (`aws.PollyTTS`).

Local: Kokoro-82M (Apache-2.0, D-39) in the box's `venvs/tts`, called through the model
runner (`_runner.py`: a subprocess in that venv, GPU lock held only while it speaks).
Writes 24 kHz mono 16-bit WAV. Voices: Kokoro's ids (`am_michael` default, `af_heart`,
`bf_emma`, ...); the first letter picks the accent (a = American, b = British).
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from . import _runner

DEFAULT_VOICE = "am_michael"


class TTS(Protocol):
    def synthesize(self, text: str, out_path: Path, *, voice: str | None = None) -> Path:
        """Speak `text` into a WAV at `out_path`; return the path."""
        ...


class LocalTTS:
    """Kokoro through the model runner; NotConfiguredError when REPLAY_MODEL_VENVS has no
    `tts` venv."""

    def __init__(self, voice: str | None = None):
        self.voice = voice or DEFAULT_VOICE
        self.last: dict = {}  # the runner's timings for the last call (load_s, per item)

    def synthesize(self, text: str, out_path: Path, *, voice: str | None = None) -> Path:
        self.synthesize_many([(text, Path(out_path))], voice=voice)
        return Path(out_path)

    def synthesize_many(self, items: list[tuple[str, Path]], *, voice: str | None = None) -> dict:
        """One model load for a batch of (text, out_path)."""
        _runner.require("tts", "tts")  # NotConfiguredError naming REPLAY_MODEL_VENVS
        req = {
            "voice": voice or self.voice,
            "items": [{"text": t, "out": str(p)} for t, p in items],
        }
        self.last = _runner.call("tts", req)
        return self.last
