"""Broadcast audio: game audio on the source clock, ducked under replays, procedural
replay stings, and an optional narration track the game audio ducks under.

Everything is generated here (no sound files ship): the sting is a short two-chord
synth figure with a soft low thump — deliberately no noise "whoosh".
"""

from __future__ import annotations

import shutil
import subprocess
import wave
from pathlib import Path

import numpy as np

SR = 48000


def _ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if exe is None:
        raise RuntimeError("ffmpeg not found on PATH")
    return exe


def read_audio(path: Path, t0: float = 0.0, dur: float | None = None) -> np.ndarray:
    """(N, 2) float32 at SR from any media file; zeros if it has no audio stream."""
    cmd = [_ffmpeg(), "-v", "error", "-ss", f"{t0:.3f}"]
    if dur is not None:
        cmd += ["-t", f"{dur:.3f}"]
    cmd += ["-i", str(path), "-vn", "-ac", "2", "-ar", str(SR), "-f", "f32le", "-"]
    res = subprocess.run(cmd, capture_output=True, check=False)
    a = np.frombuffer(res.stdout, dtype=np.float32).reshape(-1, 2).copy()
    n = round((dur or 0) * SR) if dur is not None else len(a)
    if len(a) < n:  # silent / missing / short stream: pad with silence
        a = np.vstack([a, np.zeros((n - len(a), 2), np.float32)])
    return a[:n] if dur is not None else a


def write_wav(path: Path, a: np.ndarray) -> Path:
    pcm = (np.clip(a, -1.0, 1.0) * 32767).astype("<i2")
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    return path


def sting(kind: str = "in", seconds: float = 1.1) -> np.ndarray:
    """Procedural replay sting (N, 2): a bright rising two-chord figure for "in", the
    falling mirror for "out", over a short sub thump. Deterministic."""
    n = int(seconds * SR)
    t = np.arange(n) / SR
    roots = (293.66, 392.0) if kind == "in" else (392.0, 293.66)  # D4 -> G4 or back
    out = np.zeros(n)
    for k, root in enumerate(roots):
        start = 0.0 if k == 0 else 0.14
        tt = np.clip(t - start, 0.0, None)
        env = (1 - np.exp(-tt / 0.008)) * np.exp(-tt / 0.32) * (t >= start)
        for mult, amp in ((1.0, 1.0), (1.5, 0.55), (2.0, 0.35), (3.0, 0.12)):  # root, 5th, 8ve
            out += amp * env * np.sin(2 * np.pi * root * mult * tt)
    thump = np.exp(-t / 0.09) * np.sin(2 * np.pi * (70 - 25 * t) * t)
    out = 0.16 * out / np.max(np.abs(out)) + 0.22 * thump
    pan = np.column_stack([out * 0.95, out])  # a touch of width
    return pan.astype(np.float32)


def _ramp_gain(n: int, windows: list[tuple[float, float]], gain: float, ramp_s: float = 0.3):
    """Per-sample gain: 1 outside `windows` (seconds), `gain` inside, with linear ramps."""
    g = np.ones(n, dtype=np.float32)
    r = max(1, int(ramp_s * SR))
    idx = np.arange(n)
    for a, b in windows:
        i0, i1 = int(a * SR), int(b * SR)
        inside = np.clip((idx - (i0 - r)) / r, 0, 1) * np.clip(((i1 + r) - idx) / r, 0, 1)
        g = np.minimum(g, (1 - (1 - gain) * inside).astype(np.float32))
    return g


def envelope(x: np.ndarray, attack_s: float = 0.05, release_s: float = 0.4) -> np.ndarray:
    """Peak follower of |x| (mono, N) with separate attack / release, at 1 kHz then
    upsampled — cheap and smooth enough for ducking."""
    hop = SR // 1000
    m = np.abs(x[: len(x) // hop * hop]).reshape(-1, hop).max(axis=1) if len(x) >= hop else x
    a_att, a_rel = np.exp(-1 / (1000 * attack_s)), np.exp(-1 / (1000 * release_s))
    env = np.zeros(len(m), dtype=np.float32)
    level = 0.0
    for i, v in enumerate(m):
        coef = a_att if v > level else a_rel
        level = coef * level + (1 - coef) * float(v)
        env[i] = level
    full = np.repeat(env, hop)
    return np.pad(full, (0, max(0, len(x) - len(full))), mode="edge")[: len(x)]


def duck_under(game: np.ndarray, voice: np.ndarray, depth_db: float = -12.0) -> np.ndarray:
    """Sidechain duck: game gain falls to `depth_db` while the narration speaks."""
    env = envelope(voice.mean(axis=1))
    on = np.clip(env / max(float(env.max()), 1e-6) * 4.0, 0.0, 1.0)  # ~-12 dB of voice = full
    gain = 1.0 - (1.0 - 10 ** (depth_db / 20)) * on
    return game * gain[:, None]


def mix(
    source: Path,
    t0: float,
    t1: float,
    replays: list[tuple[float, float]],
    *,
    narration: Path | None = None,
    replay_duck_db: float = -9.0,
) -> np.ndarray:
    """The rendition's audio for source seconds [t0, t1).

    `replays` are (start, end) in source seconds: game audio continues under them,
    ducked by `replay_duck_db`, with a sting at each edge. `narration` (a WAV on the
    same source clock, from t = 0) is mixed on top and the game ducks under it."""
    dur = t1 - t0
    game = read_audio(source, t0, dur)
    n = len(game)
    local = [(max(a - t0, 0.0), min(b - t0, dur)) for a, b in replays if b > t0 and a < t1]
    game = game * _ramp_gain(n, local, 10 ** (replay_duck_db / 20))[:, None]
    out = game.copy()
    for a, b in local:
        for at, kind in ((a, "in"), (b, "out")):
            s = sting(kind)
            i0 = int((at - 0.25) * SR)  # the chord lands as the wipe covers the frame
            lo, hi = max(i0, 0), min(i0 + len(s), n)
            if hi > lo:
                out[lo:hi] += s[lo - i0 : hi - i0]
    if narration is not None and Path(narration).is_file():
        voice = read_audio(Path(narration), t0, dur)
        out = duck_under(out, voice) + voice
    peak = float(np.max(np.abs(out))) if len(out) else 0.0
    if peak > 0.98:  # soft limiter, only when it would clip
        out = np.tanh(out * 1.2) / np.tanh(1.2)
    return out.astype(np.float32)
