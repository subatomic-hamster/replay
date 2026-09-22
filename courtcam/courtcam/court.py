"""Stages 5 & 7 — court coordinates and the on-court filter (plan §4.4 steps 5, 7)."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path

import cv2
import numpy as np

from .calibrate import project
from .profiles import Profile
from .track import Tracklet


@dataclass(frozen=True, slots=True)
class CourtTrack:
    """A tracklet with its foot point projected to court metres and smoothed."""

    tracklet: Tracklet
    court_m: np.ndarray  # (N, 2) smoothed court metres
    inside_fraction: float

    @property
    def track_id(self) -> int:
        return self.tracklet.track_id

    @property
    def score(self) -> float:
        """Lifetime-weighted on-court score used to cap at `players.max`."""
        return self.tracklet.lifetime_s * self.inside_fraction

    def court_at(self, t: float) -> np.ndarray:
        ts = self.tracklet.times
        return np.asarray([np.interp(t, ts, self.court_m[:, i]) for i in range(2)])


def moving_average(points: np.ndarray, window: int) -> np.ndarray:
    """Centred moving average over an (N, D) array; edges use a shrinking window."""
    if window <= 1 or len(points) <= 2:
        return points.astype(np.float64)
    pad = window // 2
    padded = np.pad(points.astype(np.float64), ((pad, pad), (0, 0)), mode="edge")
    kernel = np.ones(2 * pad + 1) / (2 * pad + 1)
    return np.column_stack(
        [np.convolve(padded[:, d], kernel, mode="valid") for d in range(points.shape[1])]
    )


def inside(points: np.ndarray, polygon: np.ndarray, margin_m: float) -> np.ndarray:
    """Boolean mask of points inside `polygon` grown by `margin_m` (signed distance)."""
    poly = np.asarray(polygon, dtype=np.float32).reshape(-1, 1, 2)
    return np.asarray(
        [cv2.pointPolygonTest(poly, (float(p[0]), float(p[1])), True) >= -margin_m for p in points]
    )


def to_court(
    tracklets: list[Tracklet], h: np.ndarray, *, smooth_window: int = 5
) -> list[np.ndarray]:
    """Project each tracklet's foot points through `h` and smooth them."""
    return [moving_average(project(t.feet_px(), h), smooth_window) for t in tracklets]


def on_court(
    tracklets: list[Tracklet],
    h: np.ndarray,
    profile: Profile,
    court_polygon_m: np.ndarray,
) -> list[CourtTrack]:
    """Keep tracklets that live on the court, capped at `players.max` (§4.4 step 5).

    Drops spectators, the bench and passers-by: without this, select mode is unusable.
    """
    cfg = profile.tracking
    kept: list[CourtTrack] = []
    for tracklet, court_m in zip(
        tracklets, to_court(tracklets, h, smooth_window=cfg.smooth_window), strict=True
    ):
        frac = float(np.mean(inside(court_m, court_polygon_m, profile.court.margin_m)))
        if frac < cfg.oncourt_min_fraction or tracklet.lifetime_s < cfg.min_lifetime_s:
            continue
        kept.append(CourtTrack(tracklet, court_m, frac))
    kept.sort(key=lambda c: c.score, reverse=True)
    return sorted(kept[: profile.players.max], key=lambda c: c.tracklet.t_start)


def resample(track: CourtTrack, times: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Boxes (px), court metres and confidence sampled on `times`, restricted to the
    tracklet's own lifetime. Returns (boxes, court, conf) with NaN outside it."""
    t = track.tracklet
    live = (times >= t.t_start) & (times <= t.t_end)
    boxes = np.full((len(times), 4), np.nan)
    court = np.full((len(times), 2), np.nan)
    conf = np.full(len(times), np.nan)
    if live.any():
        sel = times[live]
        boxes[live] = np.column_stack([np.interp(sel, t.times, t.boxes[:, i]) for i in range(4)])
        court[live] = np.column_stack(
            [np.interp(sel, t.times, track.court_m[:, i]) for i in range(2)]
        )
        conf[live] = np.interp(sel, t.times, t.confs)
    return boxes, court, conf


def with_tracklet(track: CourtTrack, tracklet: Tracklet, court_m: np.ndarray) -> CourtTrack:
    return replace(track, tracklet=tracklet, court_m=court_m)


# --- io ---------------------------------------------------------------------

COURT_SCHEMA = "courtcam.court.v1"


def track_json(track: CourtTrack) -> dict:
    t = track.tracklet
    return {
        "track_id": t.track_id,
        "inside_fraction": round(track.inside_fraction, 4),
        "frames": t.frames.tolist(),
        "times": [round(v, 4) for v in t.times.tolist()],
        "boxes": [[round(v, 2) for v in b] for b in t.boxes.tolist()],
        "confs": [round(v, 4) for v in t.confs.tolist()],
        "court": [[round(v, 4) for v in c] for c in track.court_m.tolist()],
    }


def track_from_json(d: dict) -> CourtTrack:
    return CourtTrack(
        tracklet=Tracklet(
            track_id=int(d["track_id"]),
            frames=np.asarray(d["frames"], dtype=np.int64),
            times=np.asarray(d["times"], dtype=np.float64),
            boxes=np.asarray(d["boxes"], dtype=np.float64),
            confs=np.asarray(d["confs"], dtype=np.float64),
        ),
        court_m=np.asarray(d["court"], dtype=np.float64),
        inside_fraction=float(d["inside_fraction"]),
    )


def write_court_tracks(path, tracks: list[CourtTrack], meta: dict) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema": COURT_SCHEMA, **meta, "tracks": [track_json(t) for t in tracks]}),
        encoding="utf-8",
    )
    return path


def read_court_tracks(path: Path) -> tuple[list[CourtTrack], dict]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    tracks = [track_from_json(d) for d in raw["tracks"]]
    return tracks, {k: v for k, v in raw.items() if k != "tracks"}
