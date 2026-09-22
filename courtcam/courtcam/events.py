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

from .identity import PlayerTrack
from .profiles import Profile
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


def detect_rallies(
    video: Path, players: list[PlayerTrack], profile: Profile, calib: dict[str, Any], **_: Any
) -> list[Event]:
    """Shared net-sport rally detector."""
    # ponytail: stub. Basketball does not emit rallies, so nothing depends on it yet;
    # implement (motion energy + audio onsets, §4.4 step 10) with the first net sport.
    return []


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
