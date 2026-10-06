"""Audio stage: a 16 kHz mono WAV for ASR, the source's own audio kept as-is, and two
cheap signals from it (plan §4.4 "Events"):

* **onsets** — spectral flux (half-wave rectified log-magnitude difference) peaks above a
  rolling median + k·MAD threshold: racket/hand/ball contacts, rim hits, bounces;
* **loudness** — RMS dBFS at 10 Hz, and **hype** spikes in it: sustained rises above a
  rolling-median baseline that are broadband (crowd), not tonal (speech, a whistle).

numpy only. librosa (ISC) would do the same STFT + flux, but it pulls scipy, numba and
llvmlite into an MIT library for ~40 lines of maths.
"""

from __future__ import annotations

import subprocess
import wave
from pathlib import Path

import numpy as np

from .ingest import _require
from .profiles import AudioCfg
from .schema import AudioDoc, Onset

SR = 16000
HOP_S = 0.01  # feature rate 100 Hz
WIN = 512  # 32 ms at 16 kHz
RATE_HZ = 10  # loudness envelope rate in audio.json


def has_audio(src: Path) -> bool:
    out = subprocess.run(
        [_require("ffprobe"), "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=index", "-of", "csv=p=0", str(src)],
        capture_output=True, text=True, check=False,
    ).stdout  # fmt: skip
    return bool(out.strip())


def extract(src: Path, wav: Path, full: Path | None = None) -> bool:
    """Write `wav` (16 kHz mono s16) and, if given, `full` (the first audio stream, stream
    copied into Matroska so any codec fits). Returns False, writing nothing, when the
    source has no audio."""
    if not has_audio(src):
        return False
    wav.parent.mkdir(parents=True, exist_ok=True)
    ff = _require("ffmpeg")
    subprocess.run(
        [ff, "-y", "-v", "error", "-i", str(src), "-vn", "-map", "0:a:0",
         "-ac", "1", "-ar", str(SR), "-c:a", "pcm_s16le", str(wav)],
        check=True, capture_output=True,
    )  # fmt: skip
    if full is not None:
        subprocess.run(
            [ff, "-y", "-v", "error", "-i", str(src), "-vn", "-map", "0:a:0", "-c:a", "copy",
             str(full)],
            check=True, capture_output=True,
        )  # fmt: skip
    return True


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    """Mono float32 in [-1, 1] and the sample rate (16-bit PCM WAV)."""
    with wave.open(str(path), "rb") as wf:
        sr, ch, width = wf.getframerate(), wf.getnchannels(), wf.getsampwidth()
        raw = wf.readframes(wf.getnframes())
    if width != 2:
        raise ValueError(f"{path}: expected 16-bit PCM, got {8 * width}-bit")
    x = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    return (x.reshape(-1, ch).mean(axis=1) if ch > 1 else x), sr


def features(x: np.ndarray, sr: int = SR) -> dict[str, np.ndarray]:
    """Frame-level (HOP_S) times, RMS dBFS, spectral flux and spectral flatness."""
    hop = int(round(HOP_S * sr))
    if len(x) < WIN:
        z = np.zeros(0)
        return {"t": z, "db": z, "flux": z, "flat": z}
    n = 1 + (len(x) - WIN) // hop
    idx = np.arange(WIN)[None, :] + hop * np.arange(n)[:, None]
    frames = x[idx] * np.hanning(WIN).astype(np.float32)
    spec = np.fft.rfft(frames, axis=1)
    mag = np.abs(spec) + 1e-7
    flux = np.r_[0.0, np.maximum(np.diff(np.log(mag), axis=0), 0.0).mean(axis=1)]
    # periodicity: the normalized autocorrelation peak at 80-400 Hz lags. One voice (a
    # shout of "Replay, clip that", a whistle) is periodic; a crowd of voices is not.
    ac = np.fft.irfft(mag**2, n=WIN, axis=1)
    lo, hi = int(sr / 400), int(sr / 80)
    voiced = ac[:, lo:hi].max(axis=1) / np.maximum(ac[:, 0], 1e-12)
    rms = np.sqrt((x[idx] ** 2).mean(axis=1))
    db = 20 * np.log10(np.maximum(rms, 1e-5))
    t = (np.arange(n) * hop + WIN / 2) / sr
    return {"t": t, "db": db, "flux": flux, "voiced": voiced}


def _rolling(a: np.ndarray, win: int, fn) -> np.ndarray:
    """`fn` over a centred window, via strided blocks (edges padded by reflection)."""
    win = max(1, win | 1)
    pad = np.pad(a, win // 2, mode="reflect") if len(a) > win // 2 else np.pad(a, win // 2, "edge")
    view = np.lib.stride_tricks.sliding_window_view(pad, win)
    return fn(view, axis=1)


def onsets(t: np.ndarray, flux: np.ndarray, cfg: AudioCfg) -> list[Onset]:
    """Local flux maxima above rolling median + k·MAD (1 s window), one per min gap."""
    if len(flux) < 5:
        return []
    win = int(1.0 / HOP_S)
    med = _rolling(flux, win, np.median)
    mad = _rolling(np.abs(flux - med), win, np.median) + 1e-6
    thr = med + cfg.onset_k * mad
    peak = (flux > thr) & (flux >= np.r_[flux[1:], 0]) & (flux > np.r_[0, flux[:-1]])
    out: list[Onset] = []
    for i in np.nonzero(peak)[0]:
        s = float((flux[i] - thr[i]) / mad[i])
        if s < cfg.onset_min_strength:
            continue
        if out and t[i] - out[-1].t < cfg.onset_min_gap_s:
            if s > out[-1].strength:
                out[-1] = Onset(t=round(float(t[i]), 3), strength=round(s, 2))
            continue
        out.append(Onset(t=round(float(t[i]), 3), strength=round(s, 2)))
    return out


def hype_segments(
    t: np.ndarray, db: np.ndarray, voiced: np.ndarray, cfg: AudioCfg
) -> list[tuple[float, float, float, float]]:
    """(t_start, t_peak, t_end, dB above baseline) for loud, sustained, aperiodic runs."""
    if len(db) < 10:
        return []
    smooth = _rolling(db, int(0.3 / HOP_S), np.mean)
    # ponytail: 20 s rolling median baseline (on a 10x decimated envelope, so a long game
    # stays a few MB); a whole game played at a roar has no spikes.
    step = 10
    base = np.interp(t, t[::step], _rolling(db[::step], int(20.0 / HOP_S / step), np.median))
    over = smooth - base
    hot = np.append(over > cfg.hype_db, False)
    out = []
    start = None
    for i, h in enumerate(hot):
        if h and start is None:
            start = i
        elif not h and start is not None:
            seg = slice(start, i)
            long = t[i - 1] - t[start] >= cfg.hype_min_s
            if long and np.median(voiced[seg]) <= cfg.hype_max_voiced:
                k = start + int(np.argmax(over[seg]))
                out.append((float(t[start]), float(t[k]), float(t[i - 1]), float(over[k])))
            start = None
    return out


def speech_segments(x: np.ndarray, sr: int, cfg: AudioCfg) -> list[tuple[float, float]]:
    """(t0, t1) of loud, periodic (voiced) stretches: where someone near the camera talks.
    The voice-trigger ASR only listens here, so a long game costs seconds, and t0 is the
    speech onset."""
    f = features(x, sr)
    if len(f["t"]) < 10:
        return []
    t = f["t"]
    step = 10
    base = np.interp(t, t[::step], _rolling(f["db"][::step], int(20.0 / HOP_S / step), np.median))
    loud = _rolling(f["db"], int(0.2 / HOP_S), np.mean) - base > cfg.speech_db
    voiced = _rolling(f["voiced"], int(0.2 / HOP_S), np.mean) > cfg.speech_min_voiced
    segs = []
    for a, b in _bool_runs(t, loud & voiced, cfg.speech_gap_s):
        if b - a >= cfg.speech_min_s:
            a, b = max(0.0, a - 0.25), b + 0.35
            while b - a > cfg.speech_max_s:  # very long talk: cut into ASR-sized pieces
                segs.append((a, a + cfg.speech_max_s))
                a += cfg.speech_max_s
            segs.append((a, b))
    return [(round(a, 3), round(b, 3)) for a, b in segs]


def _bool_runs(t: np.ndarray, hit: np.ndarray, max_gap: float) -> list[tuple[float, float]]:
    out: list[list[float]] = []
    for ti, h in zip(t, hit, strict=True):
        if not h:
            continue
        if out and ti - out[-1][1] <= max_gap:
            out[-1][1] = float(ti)
        else:
            out.append([float(ti), float(ti)])
    return [(a, b) for a, b in out]


def analyse(wav: Path | None, cfg: AudioCfg, duration_s: float) -> AudioDoc:
    """`audio.json` content (hype segments become `hype` events in the events stage)."""
    if wav is None or not Path(wav).is_file():
        return AudioDoc(has_audio=False)
    x, sr = read_wav(Path(wav))
    f = features(x, sr)
    # loudness envelope at RATE_HZ for the scrubber / commentary ducking
    ticks = np.arange(0.0, duration_s, 1.0 / RATE_HZ)
    env = np.interp(ticks, f["t"], f["db"]) if len(f["t"]) else np.full(len(ticks), -100.0)
    return AudioDoc(
        has_audio=True,
        sr=sr,
        rate_hz=RATE_HZ,
        loudness_db=[round(float(v), 1) for v in env],
        onsets=onsets(f["t"], f["flux"], cfg),
        hype=[
            tuple(round(v, 3) for v in seg)
            for seg in hype_segments(f["t"], f["db"], f["voiced"], cfg)
        ],
    )
