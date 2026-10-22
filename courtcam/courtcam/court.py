"""Stages 5 & 7 — court coordinates and the on-court filter (plan §4.4 steps 5, 7)."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path

import cv2
import numpy as np

from .calibrate import _k, focal_from_homography, pose_from_homography, project
from .distortion import distort_points, undistort_points
from .profiles import Profile, TrackingCfg
from .track import Tracklet

POLYGON_STEP_M = 0.25
"""How finely the court outline is sampled before it is bent back onto the frame."""


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


def stationary(track: CourtTrack, cfg: TrackingCfg) -> bool:
    """A seated official, the bench, a parent at the fence: alive for a long time and
    never leaving a ~0.5 m circle. No player stands that still for `stationary_min_s`.

    The on-court test cannot catch these on its own: the scorer's table is inside the
    court polygon on the Kennesaw calibration and the bench sits inside the 1 m margin,
    and because they never move they out-scored real players for the concurrency cap.
    """
    if track.tracklet.lifetime_s < cfg.stationary_min_s:
        return False
    c = track.court_m
    radius = np.linalg.norm(c - np.median(c, axis=0), axis=1)
    return float(np.percentile(radius, 90)) < cfg.stationary_max_m


def bystander(track: CourtTrack, polygon_m: np.ndarray, cfg: TrackingCfg) -> bool:
    """Not a player, whatever the on-court test said: never moves (`stationary`), or
    lives mostly *outside the painted lines* and inside only the margin - the bench at
    the Kennesaw baseline, the next pickleball court's baseline. Judged on merged
    players; a single fragment of a player chasing a ball out is fine."""
    strict = float(np.mean(inside(track.court_m, polygon_m, 0.0)))
    return stationary(track, cfg) or strict < cfg.inside_min_fraction


def to_court(
    tracklets: list[Tracklet],
    h: np.ndarray,
    *,
    smooth_window: int = 5,
    k1: float = 0.0,
    image_size: tuple[int, int] | None = None,
) -> list[np.ndarray]:
    """Project each tracklet's foot points through `h` and smooth them.

    `h` maps *undistorted* pixels to metres, so a lens with `k1 != 0` has its foot
    points straightened first — on the fisheye clips that is worth metres at the frame
    edge, which is exactly where the sidelines are (samples/real/RESULTS.md).
    """
    return [
        moving_average(
            project(undistort_points(t.feet_px(), k1, image_size) if k1 else t.feet_px(), h),
            smooth_window,
        )
        for t in tracklets
    ]


def polygon_px(
    polygon_m: np.ndarray,
    h_inv: np.ndarray,
    *,
    k1: float = 0.0,
    image_size: tuple[int, int] | None = None,
    step_m: float = POLYGON_STEP_M,
) -> np.ndarray:
    """The court outline in frame pixels, as a polyline that follows the painted lines.

    A straight court line is a curve on a fisheye frame, so each edge is sampled every
    `step_m` and bent back through the lens; the four-corner version would cut the
    corner by tens of pixels. With `k1 == 0` this is the old four corners, re-sampled.
    """
    poly = np.asarray(polygon_m, dtype=np.float64)
    edges = [
        np.linspace(a, b, max(int(np.ceil(np.linalg.norm(b - a) / step_m)), 1), endpoint=False)
        for a, b in zip(poly, np.roll(poly, -1, axis=0), strict=True)
    ]
    px = project(np.vstack(edges), h_inv)
    return distort_points(px, k1, image_size) if k1 else px


FIT_MIN_ON_COURT = 0.35
"""A court fit is trusted only if at least this share of moving people's time (tracklets
that pass `min_lifetime_s` and are not `stationary`) is on its court. Right fits:
0.57-0.69 on the CC BY Nottingham game, the 3x3 Usti clip and the volleyball clip (the
rest is the bench and passers-by), 0.998 on the 2v2 park ground plane; the autocalib
proposals that were wrong: 0.0 (2v2 park) and 0.13 (3x3)."""

FIT_MIN_HEIGHT = 0.4
"""... and at least this share of person boxes is 0.6-1.6x the height a 1.75 m person
on that foot point would be in the camera the homography implies. Right fits 0.64-0.997;
the wrong Nottingham half-court proposal 0.0 (people 3x shorter than its camera says),
which the on-court test cannot see: it squeezes the whole floor into the court."""

PERSON_M = 1.75


def _height_share(
    boxes: np.ndarray, h: np.ndarray, k1: float, image_size: tuple[int, int]
) -> float | None:
    """Share of `boxes` (xywh px) 0.6-1.6x as tall as a PERSON_M person standing at the
    box's foot point would be; None when the homography implies no camera."""

    h_inv = np.linalg.inv(h)
    f = focal_from_homography(h_inv, image_size)
    if f is None or not len(boxes):
        return None
    k = _k(f, image_size)
    r, t = pose_from_homography(h_inv, k)
    feet = np.c_[boxes[:, 0] + boxes[:, 2] / 2, boxes[:, 1] + boxes[:, 3]]
    head = np.c_[feet[:, 0], boxes[:, 1]]
    if k1:
        feet, head = undistort_points(feet, k1, image_size), undistort_points(head, k1, image_size)
    ground = project(feet, h)
    top = (k @ (r @ np.c_[ground, np.full(len(ground), PERSON_M)].T + t[:, None])).T
    pred = feet[:, 1] - top[:, 1] / top[:, 2]
    ratio = (feet[:, 1] - head[:, 1]) / np.where(np.abs(pred) > 1.0, pred, np.nan)
    return float(np.mean((ratio > 0.6) & (ratio < 1.6)))


def fit_check(
    tracklets: list[Tracklet],
    h: np.ndarray,
    profile: Profile,
    court_polygon_m: np.ndarray,
    *,
    k1: float = 0.0,
    image_size: tuple[int, int] | None = None,
) -> dict:
    """Does the court fit agree with the people (D-94)? A wrong fit must never decide who
    is a player: `trusted` false turns the on-court filter off (`on_court(trusted=)`)."""
    cfg = profile.tracking
    moving = on = 0.0
    boxes = []
    for tracklet, court_m in zip(
        tracklets,
        to_court(tracklets, h, smooth_window=cfg.smooth_window, k1=k1, image_size=image_size),
        strict=True,
    ):
        if tracklet.lifetime_s < cfg.min_lifetime_s:
            continue
        frac = float(np.mean(inside(court_m, court_polygon_m, profile.court.margin_m)))
        if stationary(CourtTrack(tracklet, court_m, frac), cfg):
            continue
        moving += tracklet.lifetime_s
        on += tracklet.lifetime_s * (frac >= cfg.oncourt_min_fraction)
        boxes.append(tracklet.boxes)
    share = on / moving if moving else None
    tall = _height_share(np.vstack(boxes), h, k1, image_size) if boxes and image_size else None
    trusted = (share is None or share >= FIT_MIN_ON_COURT) and (
        tall is None or tall >= FIT_MIN_HEIGHT
    )
    return {
        "trusted": bool(trusted),
        "on_court_share": None if share is None else round(share, 3),
        "height_share": None if tall is None else round(tall, 3),
    }


def on_court(
    tracklets: list[Tracklet],
    h: np.ndarray,
    profile: Profile,
    court_polygon_m: np.ndarray,
    *,
    k1: float = 0.0,
    image_size: tuple[int, int] | None = None,
    trusted: bool = True,
) -> list[CourtTrack]:
    """Keep tracklets that live on the court (§4.4 step 5).

    Drops spectators, the bench and passers-by: without this, select mode is unusable.
    A tracklet that never moves is dropped here too (`stationary`), before it can be
    merged into a player; `identity` repeats the test on merged players for the
    officials whose track breaks into pieces shorter than `stationary_min_s`.

    `players.max` is *not* applied here. Real footage breaks one player into a dozen
    tracklets, so capping before `identity` merges them keeps whoever happened to get
    the longest unbroken track and throws the rest of the roster away; the cap belongs
    on merged players (`identity.identify`). `tracking.max_candidates` is only a guard
    on the O(n^2) merge.

    `trusted` false (`fit_check`: the fit disagrees with the people) keeps everyone who
    moves, on court or not: a bench in the list beats players dropped by a wrong court.
    """
    cfg = profile.tracking
    kept: list[CourtTrack] = []
    for tracklet, court_m in zip(
        tracklets,
        to_court(tracklets, h, smooth_window=cfg.smooth_window, k1=k1, image_size=image_size),
        strict=True,
    ):
        frac = float(np.mean(inside(court_m, court_polygon_m, profile.court.margin_m)))
        if not trusted:
            frac = 1.0
        if frac < cfg.oncourt_min_fraction or tracklet.lifetime_s < cfg.min_lifetime_s:
            continue
        track = CourtTrack(tracklet, court_m, frac)
        if not stationary(track, cfg):
            kept.append(track)
    kept.sort(key=lambda c: c.score, reverse=True)
    return sorted(kept[: cfg.max_candidates], key=lambda c: c.tracklet.t_start)


def resample(
    track: CourtTrack, times: np.ndarray, max_gap_s: float = np.inf
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Boxes (px), court metres and confidence sampled on `times`, restricted to the
    tracklet's own lifetime and to gaps between its samples of at most `max_gap_s`.
    Returns (boxes, court, conf) with NaN elsewhere."""
    t = track.tracklet
    live = (times >= t.t_start) & (times <= t.t_end)
    if np.isfinite(max_gap_s) and live.any():
        k = np.clip(np.searchsorted(t.times, times[live]), 1, len(t.times) - 1)
        gap = t.times[k] - t.times[k - 1]
        on = np.isclose(t.times[k], times[live]) | np.isclose(t.times[k - 1], times[live])
        live[np.flatnonzero(live)] = on | (gap <= max_gap_s)
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
