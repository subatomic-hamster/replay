"""Stage 10 — event detection (plan §4.4 step 10).

Which detectors run comes from the profile's `events:` list, never from the sport id.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import cv2
import numpy as np

from .court import moving_average, resample
from .identity import PlayerTrack
from .profiles import Profile, RallyCfg
from .schema import Event


@dataclass(frozen=True, slots=True)
class ShotCandidate:
    t_key: float
    player_id: str | None
    court: tuple[float, float] | None
    confidence: float


class Labeler(Protocol):
    """Turns a clip around `t_key` into shot facts. The default one cannot see the
    video, so it leaves `made` unknown; a VLM labeler fills it in (§4.4 step 10)."""

    source: str

    def label(self, video: Path, candidate: ShotCandidate) -> dict[str, Any]: ...


class HeuristicLabeler:
    """Pass-through: keeps the heuristic's own confidence, `made` stays unknown."""

    source = "heuristic"

    def label(self, video: Path, candidate: ShotCandidate) -> dict[str, Any]:
        return {"is_shot": True, "made": None, "confidence": candidate.confidence}


# --- rim motion -------------------------------------------------------------


def rim_energy(
    video: Path,
    rim_px: tuple[float, float],
    *,
    roi_px: int,
    stride: int,
    active: Callable[[float], bool] | None = None,
    fps: float = 30.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Frame-differencing energy inside the rim ROI. Returns (times, energy).

    Frames where `active(t)` is False are grabbed but never decoded, so a long game
    only pays for the moments a player is actually near the basket.
    """
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise FileNotFoundError(f"cannot open {video}")
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cx, cy = int(round(rim_px[0])), int(round(rim_px[1]))
    x0, x1 = max(0, cx - roi_px), min(w, cx + roi_px)
    y0, y1 = max(0, cy - roi_px), min(h, cy + roi_px)
    times: list[float] = []
    energy: list[float] = []
    prev: np.ndarray | None = None
    i = -1
    try:
        if x1 <= x0 or y1 <= y0:  # rim projects outside the frame
            return np.zeros(0), np.zeros(0)
        while True:
            ok = cap.grab()
            if not ok:
                break
            i += 1
            if i % stride:
                continue
            t = i / fps
            if active is not None and not active(t):
                prev = None
                continue
            ok, frame = cap.retrieve()
            if not ok:
                break
            roi = cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY).astype(np.float32)
            if prev is not None and prev.shape == roi.shape:
                times.append(t)
                energy.append(float(np.mean(np.abs(roi - prev))))
            prev = roi
    finally:
        cap.release()
    return np.asarray(times), np.asarray(energy)


def bursts(
    times: np.ndarray, energy: np.ndarray, *, sigma: float, min_gap_s: float
) -> list[tuple[float, float]]:
    """Local maxima above mean + sigma*std, thinned to one per `min_gap_s`.

    Returns (time, z-score) pairs, strongest first within each gap window.
    """
    if len(energy) < 3:
        return []
    mu, sd = float(np.mean(energy)), float(np.std(energy))
    if sd <= 1e-6:
        return []
    z = (energy - mu) / sd
    order = np.argsort(z)[::-1]
    picked: list[tuple[float, float]] = []
    for i in order:
        if z[i] < sigma:
            break
        t = float(times[i])
        if any(abs(t - pt) < min_gap_s for pt, _ in picked):
            continue
        picked.append((t, float(z[i])))
    return sorted(picked)


# --- detectors --------------------------------------------------------------


def detect_shots(
    video: Path,
    players: list[PlayerTrack],
    profile: Profile,
    calib: dict[str, Any],
    *,
    fps: float = 30.0,
    labeler: Labeler | None = None,
) -> list[Event]:
    """Foot point within `shot.rim_radius_m` of the rim + a motion burst in the rim ROI."""
    rim_m = calib.get("rim_m")
    rim_px = calib.get("rim_px")
    if rim_m is None or rim_px is None:
        return []
    cfg = profile.shot
    labeler = labeler or HeuristicLabeler()
    rim = np.asarray(rim_m, dtype=np.float64)

    def nearest(t: float) -> tuple[PlayerTrack | None, np.ndarray | None, float]:
        best, best_pos, best_d = None, None, np.inf
        for p in players:
            if not (p.t_start <= t <= p.t_end):
                continue
            pos = p.track.court_at(t)
            d = float(np.linalg.norm(pos - rim))
            if d < best_d:
                best, best_pos, best_d = p, pos, d
        return best, best_pos, best_d

    def active(t: float) -> bool:
        return nearest(t)[2] <= cfg.rim_radius_m

    # ponytail: mean abs frame difference in the rim ROI. It fires on any motion there,
    # so a defender under the basket scores like a shot; `shot.burst_sigma` is the knob
    # and the plan says to tune it on real footage. Measured ~1/3 precision on
    # samples/real (8 events in 240 s, 3 hand-checked); burst_sigma was left alone
    # because the events land in the right place at the wrong moment, and the metre
    # gate that would help needs a lens model first. Upgrade path: vertical optical flow
    # in the ROI, or hand the candidates to a VLM labeler (the `Labeler` seam is here).
    times, energy = rim_energy(
        video,
        tuple(rim_px),
        roi_px=cfg.roi_px,
        stride=profile.detection.stride,
        active=active if players else None,
        fps=fps,
    )
    events: list[Event] = []
    for n, (t_key, z) in enumerate(
        bursts(times, energy, sigma=cfg.burst_sigma, min_gap_s=cfg.min_gap_s)
    ):
        player, pos, dist = nearest(t_key)
        if player is None or dist > cfg.rim_radius_m:
            continue
        candidate = ShotCandidate(
            t_key=t_key,
            player_id=player.player_id,
            court=(float(pos[0]), float(pos[1])),
            confidence=float(min(0.95, 0.4 + 0.1 * (z - cfg.burst_sigma))),
        )
        label = labeler.label(video, candidate)
        if not label.get("is_shot", True):
            continue
        events.append(
            Event(
                id=f"e_{n:04d}",
                type="shot",
                t_start=round(max(0.0, t_key - cfg.pre_s), 3),
                t_key=round(t_key, 3),
                t_end=round(t_key + cfg.post_s, 3),
                made=label.get("made"),
                player_id=label.get("shooter_player_id", candidate.player_id),
                court=(round(candidate.court[0], 3), round(candidate.court[1], 3)),
                confidence=round(float(label.get("confidence", candidate.confidence)), 3),
                source=getattr(labeler, "source", "heuristic"),
                confirmed=False,
            )
        )
    return events


def court_activity(
    players: list[PlayerTrack], *, rate_hz: float, smooth_s: float, max_speed_mps: float
) -> tuple[np.ndarray, np.ndarray]:
    """Median court speed (m/s) of the players on court at each tick, smoothed.

    Median, not mean: one player strolling to pick up the shuttle is not a rally, and
    one tracker jump does not drag the other three along. Speeds above `max_speed_mps`
    are an id switch or a homography jump, not a person, and are dropped.
    Returns (times, speed).
    """
    if not players:
        return np.zeros(0), np.zeros(0)
    times = np.arange(0.0, max(p.t_end for p in players) + 1e-9, 1.0 / rate_hz)
    speeds = np.full((len(players), len(times)), np.nan)
    for i, p in enumerate(players):
        _, court, _ = resample(p.track, times)
        if len(times) > 1:
            speeds[i] = np.linalg.norm(np.gradient(court, axis=0), axis=1) * rate_hz
    speeds[speeds > max_speed_mps] = np.nan
    live = np.isfinite(speeds).any(axis=0)
    median = np.zeros(len(times))
    median[live] = np.nanmedian(speeds[:, live], axis=0)
    return times, moving_average(median[:, None], max(1, int(round(smooth_s * rate_hz))))[:, 0]


def rally_segments(
    times: np.ndarray, activity: np.ndarray, cfg: RallyCfg
) -> list[tuple[float, float, float]]:
    """Runs above `off_mps` that peak above `on_mps`. A run ends `tail_s` after its last
    peak above `on_mps` — the walk back after a point is still above `off_mps` — then
    gaps under `max_gap_s` are bridged and runs under `min_duration_s` dropped.
    Returns (start, end, peak) per rally."""
    runs: list[list[float]] = []
    start = None
    for i, a in enumerate(np.append(activity, -np.inf)):
        if start is None and a > cfg.off_mps:
            start = i
        elif start is not None and a <= cfg.off_mps:
            hot = np.nonzero(activity[start:i] >= cfg.on_mps)[0]
            if len(hot):
                t0 = float(times[start])
                t1 = min(float(times[i - 1]), float(times[start + hot[-1]]) + cfg.tail_s)
                peak = float(activity[start:i].max())
                if runs and t0 - runs[-1][1] < cfg.max_gap_s:
                    runs[-1][1], runs[-1][2] = t1, max(runs[-1][2], peak)
                else:
                    runs.append([t0, t1, peak])
            start = None
    return [(t0, t1, pk) for t0, t1, pk in runs if t1 - t0 >= cfg.min_duration_s]


def detect_rallies(
    video: Path, players: list[PlayerTrack], profile: Profile, calib: dict[str, Any], **_: Any
) -> list[Event]:
    """Shared net-sport rally detector: bursts of player movement on court (plan §4.4
    step 10). Nothing sport-specific; the thresholds are the profile's `rally:` block."""
    # ponytail: motion only — no audio onsets, so `contacts` stays null. Ceiling: a
    # slow dinking exchange looks like people standing still. Upgrade: count racket
    # transients in the rally window with `expected_contact_hz` as the gate.
    cfg = profile.rally
    times, activity = court_activity(
        players, rate_hz=cfg.rate_hz, smooth_s=cfg.smooth_s, max_speed_mps=cfg.max_speed_mps
    )
    return [
        Event(
            id=f"e_{n:04d}",
            type="rally",
            t_start=round(max(0.0, t0 - cfg.lead_s), 3),
            t_key=round(max(0.0, t0 - cfg.lead_s), 3),
            t_end=round(t1, 3),
            confidence=round(min(0.95, 0.5 + 0.2 * (peak / cfg.on_mps - 1.0)), 3),
            source="heuristic",
        )
        for n, (t0, t1, peak) in enumerate(rally_segments(times, activity, cfg))
    ]


DETECTORS: dict[str, Callable[..., list[Event]]] = {
    "shot": detect_shots,
    "rally": detect_rallies,
}


def detect_events(
    video: Path,
    players: list[PlayerTrack],
    profile: Profile,
    calib: dict[str, Any],
    *,
    fps: float = 30.0,
    labeler: Labeler | None = None,
) -> list[Event]:
    """Run every detector the profile enables and renumber the merged result."""
    out: list[Event] = []
    for name in profile.events:
        detector = DETECTORS.get(name)
        if detector is None:
            raise ValueError(f"{profile.id}: no detector registered for event type {name!r}")
        out += detector(video, players, profile, calib, fps=fps, labeler=labeler)
    out.sort(key=lambda e: e.t_key)
    for n, e in enumerate(out):
        e.id = f"e_{n:04d}"
    return out
