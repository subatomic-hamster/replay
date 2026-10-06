"""Synthesize the voice-trigger clips in `samples/synthetic/voice/` with a local TTS.

Run once, on the box, in the TTS venv (Kokoro-82M, Apache-2.0 code and weights):

    HF_HOME=/workspace/wt/replay-env/hf /workspace/wt/replay-env/venvs/tts/bin/python \\
        samples/synthetic/make_voice.py

Writes `<slug>.wav` (16 kHz mono PCM, what `courtcam.synth` mixes in) for "Replay, clip
that" and "Replay, clip <name>" for every roster name, plus `manifest.json` recording
the engine and voice. The clips are committed, so CI and the generator never need the
TTS; without them the generator falls back to a tone pattern labelled `tone-fallback`.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf
from courtcam.synth import NAMES, voice_slug
from kokoro import KPipeline

OUT = Path(__file__).resolve().parent / "voice"
VOICES = ("am_michael", "af_heart")  # alternate so speaker tests get two voices


def main() -> None:
    OUT.mkdir(exist_ok=True)
    pipe = KPipeline(lang_code="a", device="cpu", repo_id="hexgrad/Kokoro-82M")
    texts = ["Replay, clip that"] + [f"Replay, clip {n}" for n in NAMES]
    manifest = {
        "engine": "kokoro 0.9.4 (hexgrad/Kokoro-82M, Apache-2.0)",
        "note": "synthetic speech for courtcam.synth voice triggers; 16 kHz mono",
        "clips": [],
    }
    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg, "ffmpeg resamples 24 kHz -> 16 kHz"
    for k, text in enumerate(texts):
        voice = VOICES[k % len(VOICES)]
        wav = np.concatenate([a.numpy() for _, _, a in pipe(text + ".", voice=voice)])
        dest = OUT / f"{voice_slug(text)}.wav"
        with tempfile.NamedTemporaryFile(suffix=".wav") as tmp:
            sf.write(tmp.name, wav, 24000)
            subprocess.run(
                [ffmpeg, "-y", "-v", "error", "-i", tmp.name, "-ar", "16000", "-ac", "1",
                 "-c:a", "pcm_s16le", str(dest)],
                check=True,
            )  # fmt: skip
        manifest["clips"].append(
            {"file": dest.name, "text": text, "voice": voice, "seconds": round(len(wav) / 24000, 3)}
        )
        print(dest.name, voice, f"{len(wav) / 24000:.2f}s")  # ttsr-ignore: py/no-print (CLI script)
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
