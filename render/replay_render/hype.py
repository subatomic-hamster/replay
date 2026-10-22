"""Hype meter (vision item 25): a 0-1 excitement series for the scrubber, plus highlight
candidates where it peaks.

Three cues, each scored 0-1 at the tracks rate (10 Hz), fused as a noisy-or and published
at `RATE_HZ`:

* **audio** — courtcam's `hype` events (broadband, sustained, unvoiced loudness spikes:
  crowd, not speech) at their confidence, over a loudness score (dB above its own 20 s
  rolling median) that counts `LOUDNESS_WITH_HYPE` of full when courtcam's audio stage
  ran (it cannot tell a cheer from a nearby "Replay, clip that"), and in full when there
  is no audio.json and the loudness is measured from the video.
* **arms_up** — players with both wrists above their shoulders (`poses/`), the
  celebration pose; two players at once is a full score. Ignored inside shots (release
  and contest), blocks and overhead contacts, where raised arms are the play itself.
* **speed** — a burst of the fast players' speed over its own 30 s baseline (jumping,
  running to a teammate). Weak on its own: a fast break looks the same, so it weighs least.
* **plays** (D-90) — the detected plays themselves (`events.json`): a make by its points,
  a block, a steal. A quiet gym with a good camera is all plays; a loud one adds the
  cheer on top. Nottingham Q1 (CC BY): top-5 precision 0.2 -> 0.4 (docs/decisions.md D-90).

Candidates are local maxima of the fused series, at least `MIN_GAP_S` apart, each mapped
to the play that ended just before the peak (the cheer follows the play), else a window
around the peak. Heuristic, uncalibrated: weights are reasoned, not fitted.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np

from .gamedata import Game, read_json

RATE_HZ = 2.0
GRID_HZ = 10.0
WEIGHTS = {"audio": 0.85, "arms_up": 0.6, "speed": 0.35, "plays": 0.9}
# D-90: what the detected play is worth on its own, by points scored (a free throw is
# rarely a highlight), and a block or steal; held for PLAY_HOLD_S from the play's key time
PLAY_VALUE = {1: 0.25, 2: 0.7, 3: 0.9}
NOTABLE_VALUE = {"block": 0.7, "steal": 0.6}
PLAY_HOLD_S = 3.0
UNKNOWN_SHARE = 0.5  # a shot of unknown outcome: half a make's value (D-92)
PLAY_FIRST = 0.3  # candidates with a play worth this much rank first (not a free throw)
LOUDNESS_WITH_HYPE = 0.4  # raw loudness's share of the audio cue when courtcam's ran
CANDIDATE_MIN = 0.4
MIN_GAP_S = 8.0
MAX_CANDIDATES = 12
PLAY_LOOKBACK_S = 8.0  # a cheer this long after a play ends still belongs to it
REL = "hype.json"


def _rolling(a: np.ndarray, win: int, fn) -> np.ndarray:
    win = max(1, int(win) | 1)
    if len(a) == 0:
        return a
    pad = np.pad(a, win // 2, mode="edge")
    return fn(np.lib.stride_tricks.sliding_window_view(pad, win), axis=1)


def _mean(a: np.ndarray, win: int) -> np.ndarray:
    return _rolling(a, win, np.mean)


def _pcm(path: Path, sr: int = 8000) -> np.ndarray:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        return np.zeros(0, np.float32)
    res = subprocess.run(
        [ffmpeg, "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(sr),
         "-f", "f32le", "-"],
        capture_output=True, check=False,
    )  # fmt: skip
    return np.frombuffer(res.stdout, dtype=np.float32)


def loudness(game_dir: Path) -> tuple[np.ndarray, np.ndarray, str] | None:
    """(times, RMS dBFS, source) at 10 Hz, or None for a silent game."""
    gd = Path(game_dir)
    doc = read_json(gd / "audio.json")
    if doc is not None:
        if not doc.get("has_audio"):
            return None
        db = np.asarray(doc.get("loudness_db") or [], dtype=np.float64)
        if len(db):
            return np.arange(len(db)) / float(doc.get("rate_hz") or 10), db, "audio.json"
    src = gd / "media" / "wide.mp4"
    x = _pcm(src) if src.is_file() else np.zeros(0, np.float32)
    hop = 800  # 0.1 s at 8 kHz
    n = len(x) // hop
    if n < 10:
        return None
    rms = np.sqrt(np.mean(np.square(x[: n * hop].reshape(n, hop), dtype=np.float64), axis=1))
    return (np.arange(n) + 0.5) / GRID_HZ, 20 * np.log10(np.maximum(rms, 1e-5)), "media/wide.mp4"


def audio_score(t: np.ndarray, db: np.ndarray) -> np.ndarray:
    """dB above the 20 s rolling median of the 1 s mean: 2 dB starts, 10 dB is full."""
    over = _mean(db, int(GRID_HZ)) - _rolling(db, int(20 * GRID_HZ), np.median)
    return np.clip((over - 2.0) / 8.0, 0.0, 1.0)


def arms_up_count(game_dir: Path) -> tuple[np.ndarray, np.ndarray] | None:
    """(times, players with both wrists above their shoulders) from poses/, or None."""
    files = sorted((Path(game_dir) / "poses").glob("*.json"))
    ts, counts = [], []
    for f in files:
        for fr in (read_json(f) or {}).get("frames", []):
            n = 0
            for p in fr.get("p", []):
                kp = np.asarray(p.get("kp") or [], dtype=np.float64)
                if kp.shape != (17, 3):
                    continue
                sh, wr, hip = kp[[5, 6]], kp[[9, 10]], kp[[11, 12]]
                if (np.r_[sh[:, 2], wr[:, 2], hip[:, 2]] < 0.3).any():
                    continue
                torso = max(float(np.mean(hip[:, 1]) - np.mean(sh[:, 1])), 1e-6)
                n += bool((wr[:, 1] < sh[:, 1] - 0.25 * torso).all())
            ts.append(float(fr["t"]))
            counts.append(n)
    if not ts:
        return None
    return np.asarray(ts), np.asarray(counts, dtype=np.float64)


def action_windows(events: list[dict]) -> list[tuple[float, float]]:
    """Where raised arms are the play, not a celebration: a shot from its start to 1 s
    after the release (shooter and contesting defenders), a block, an overhead contact."""
    out = []
    for e in events:
        kind, tk = e.get("type"), float(e.get("t_key") or 0.0)
        if kind == "shot":
            out.append((float(e.get("t_start", tk)), tk + 1.0))
        elif kind == "block":
            out.append((tk - 1.0, tk + 1.0))
        elif kind == "contact":
            out.append((tk - 0.6, tk + 0.6))
    return out


def _in_any(t: np.ndarray, windows: list[tuple[float, float]]) -> np.ndarray:
    hit = np.zeros(len(t), dtype=bool)
    for a, b in windows:
        hit |= (t >= a) & (t <= b)
    return hit


def speed_score(game: Game) -> np.ndarray:
    """Per tracks sample: the 90th-percentile player speed over its 30 s rolling median;
    1 m/s above starts, 3.5 m/s above is full. Id jumps (> 8 m/s) are dropped."""
    tr = game.tracks
    if len(tr.t) < 3:
        return np.zeros(len(tr.t))
    dt = float(np.median(np.diff(tr.t)))
    v = np.linalg.norm(np.diff(tr.court, axis=1), axis=2) / dt
    v[~(v <= 8.0)] = np.nan
    v = np.concatenate([v[:, :1], v], axis=1)
    ok = np.isfinite(v).any(axis=0)
    fast = np.zeros(v.shape[1])
    if ok.any():
        fast[ok] = np.nanpercentile(v[:, ok], 90, axis=0)
    fast = _mean(fast, round(0.5 / dt))
    base = _rolling(fast, round(30 / dt), np.median)
    return np.clip((fast - base - 1.0) / 2.5, 0.0, 1.0)


def play_score(grid: np.ndarray, events: list[dict], outside: int = 3) -> np.ndarray:
    """Per grid sample: the best detected play in the last PLAY_HOLD_S — a make by its
    kind (`PLAY_VALUE`: a free throw, inside, or from `outside` points up; inside when
    unknown), a block or steal (`NOTABLE_VALUE`). D-92: a shot whose outcome the ball
    could not tell counts half (it rolled on the rim: worth a look either way), and a
    pickup game's 1-point basket is an inside make, not a free throw."""
    out = np.zeros(len(grid))
    for e in events:
        if e.get("dismissed"):
            continue
        kind = e.get("type")
        if kind == "shot" and e.get("made") is not False:
            pts = int(e.get("points") or 0)
            v = PLAY_VALUE[1 if e.get("cause") == "free_throw" else 3 if pts >= outside else 2]
            if e.get("made") is None:
                v *= UNKNOWN_SHARE
        elif kind in NOTABLE_VALUE:
            v = NOTABLE_VALUE[kind]
        else:
            continue
        tk = float(e.get("t_key") or 0.0)
        m = (grid >= tk) & (grid <= tk + PLAY_HOLD_S)
        out[m] = np.maximum(out[m], v)
    return out


def candidates(t: np.ndarray, hype: np.ndarray, comps: dict, game: Game) -> list[dict]:
    """Greedy peaks >= CANDIDATE_MIN, >= MIN_GAP_S apart; detected plays first, each
    group best first."""
    peak = (hype >= CANDIDATE_MIN) & (hype >= np.r_[hype[1:], 0]) & (hype > np.r_[0, hype[:-1]])
    taken: list[int] = []
    for i in sorted(np.nonzero(peak)[0], key=lambda i: -hype[i]):
        if all(abs(t[i] - t[j]) >= MIN_GAP_S for j in taken):
            taken.append(int(i))
        if len(taken) >= MAX_CANDIDATES:
            break
    plays = sorted(game.plays, key=lambda p: p["t_end"])
    out = []
    for i in taken:
        tp = float(t[i])
        play = next(
            (p for p in reversed(plays) if tp - PLAY_LOOKBACK_S <= p["t_end"] <= tp + 1.0), None
        )
        t0, t1 = (play["t_start"], play["t_end"] + 1.0) if play else (tp - 6.0, tp + 2.0)
        out.append(
            {
                "t": round(tp, 2),
                "score": round(float(hype[i]), 3),
                "t_start": round(max(0.0, t0), 2),
                "t_end": round(min(game.duration, t1), 2),
                "play_id": play["id"] if play else None,
                "reasons": [k for k, c in comps.items() if c[i] >= 0.3],
                "components": {k: round(float(c[i]), 3) for k, c in comps.items()},
            }
        )
    # D-92: a detected play first (by its value), the crowd and poses only after: a
    # cheer with no play found is a guess, a make is a highlight (a free throw is not)
    out.sort(key=lambda c: (c["components"].get("plays", 0.0) < PLAY_FIRST, -c["score"]))
    return out


def _outside_points(game: Game) -> int:
    """What a basket from outside the arc is worth in this game's sport (3; 2 in a 1s
    and 2s pickup profile)."""
    try:
        from courtcam.profiles import load_profile

        return int(load_profile(game.game.get("sport") or "basketball").scoring.outside)
    except Exception:  # noqa: BLE001 — no courtcam or no such sport: full-court rules
        return 3


def hype_series(game: Game) -> dict:
    """`hype.json` (`replay.hype.v1`) for a loaded game."""
    dur = game.duration or (float(game.tracks.t[-1]) if len(game.tracks.t) else 0.0)
    grid = np.arange(0.0, dur, 1.0 / GRID_HZ)
    sources: dict[str, str | None] = {"audio": None, "arms_up": None, "speed": None, "plays": None}
    comps = {k: np.zeros(len(grid)) for k in WEIGHTS}
    loud = loudness(game.dir)
    if loud is not None:
        lt, db, sources["audio"] = loud
        # courtcam's analysis tells crowd from speech; raw loudness cannot ("Replay, clip
        # that" near the phone is loud), so with audio.json it only adds a little
        scale = LOUDNESS_WITH_HYPE if sources["audio"] == "audio.json" else 1.0
        comps["audio"] = scale * np.interp(grid, lt, audio_score(lt, db), left=0.0, right=0.0)
    for e in game.events:  # courtcam's broadband crowd spikes
        if e.get("type") == "hype" and not e.get("dismissed"):
            m = (grid >= e["t_start"]) & (grid <= e["t_end"])
            comps["audio"][m] = np.maximum(comps["audio"][m], float(e.get("confidence") or 0.5))
            sources["audio"] = sources["audio"] or "events.json"
    arms = arms_up_count(game.dir)
    if arms is not None:
        at, n = arms
        n = n * ~_in_any(at, action_windows(game.events))
        held = _rolling(np.clip(n / 2.0, 0.0, 1.0), int(GRID_HZ), np.max)  # hold 1 s
        comps["arms_up"] = np.interp(grid, at, held, left=0.0, right=0.0)
        sources["arms_up"] = "poses"
    if len(game.tracks.t) >= 3:
        comps["speed"] = np.interp(grid, game.tracks.t, speed_score(game), left=0.0, right=0.0)
        sources["speed"] = "tracks"
    comps["plays"] = play_score(grid, game.events, _outside_points(game))
    if comps["plays"].any():
        sources["plays"] = "events.json"
    keep = np.ones(len(grid))
    for k, w in WEIGHTS.items():
        keep *= 1.0 - w * comps[k]
    fused = _mean(1.0 - keep, int(GRID_HZ))
    # publish at RATE_HZ: the max of each bin, so a short spike survives the downsample
    step = int(GRID_HZ / RATE_HZ)
    nb = len(grid) // step
    t_out = np.arange(nb) / RATE_HZ
    pub = {k: c[: nb * step].reshape(nb, step).max(axis=1) for k, c in comps.items()}
    values = fused[: nb * step].reshape(nb, step).max(axis=1) if nb else np.zeros(0)
    return {
        "schema": "replay.hype.v1",
        "game_id": game.game.get("id") or game.dir.name,
        "rate_hz": RATE_HZ,
        "duration_s": round(dur, 3),
        "values": [round(float(v), 3) for v in values],
        "components": {k: [round(float(v), 3) for v in c] for k, c in pub.items()},
        "sources": sources,
        "weights": WEIGHTS,
        "candidates": candidates(t_out, values, pub, game),
        "method": "heuristic: noisy-or of audio loudness, arms-up poses, speed bursts, "
        "detected makes/blocks/steals",
    }
