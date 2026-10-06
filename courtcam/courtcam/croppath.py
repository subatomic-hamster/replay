"""Stage 8 — per-player follow-cam crop paths (plan §4.4 step 8).

One rect per video frame at 30 Hz, normalised to [0, 1], `t0 = 0`. The camera is a
critically damped spring chasing the player's box centre (through a small dead zone)
plus a short motion lead from the smoothed velocity, clamped inside the frame. Through
a tracking gap the target holds still, so the window parks and eases back when the
player reappears.
"""

from __future__ import annotations

import numpy as np

from .profiles import FollowCamCfg
from .schema import CropPath

MAX_LEAD_FRACTION = 0.25  # of the crop window, so a sprint cannot throw the frame
CROP_ASPECT = 16.0 / 9.0  # the TV viewport; a panoramic source must not letterbox it
MIN_CROP_W = 480.0  # px — below this a 1080p TV is upscaling more than 4x
# Operator feel (measured, render/README.md "Cameras"): detector jitter inside a
# band of DEAD_FRAC x the window never moves the camera, and the motion lead comes from
# an EMA of the target's velocity (time constant VEL_TAU_S), not the raw per-frame step,
# which multiplied box noise by fps x lead_s. 0 / 0 reproduces the previous camera.
DEAD_FRAC = 0.04
VEL_TAU_S = 0.4


def _targets(boxes_px: np.ndarray) -> np.ndarray:
    """Box centres with gaps (NaN rows) held at the last known centre."""
    centres = np.column_stack(
        [boxes_px[:, 0] + boxes_px[:, 2] / 2.0, boxes_px[:, 1] + boxes_px[:, 3] / 2.0]
    )
    valid = np.isfinite(centres).all(axis=1)
    if not valid.any():
        return centres
    idx = np.where(valid, np.arange(len(centres)), 0)
    np.maximum.accumulate(idx, out=idx)
    filled = centres[idx]
    first = int(np.argmax(valid))
    filled[:first] = centres[first]  # before the player appears, sit where they will be
    return filled


def court_px_width(calib: dict | None, frame_w: int) -> float | None:
    """Visible pixel width of the calibrated court polygon, or None without a calib.

    Clipped to the frame: a loose homography on a wide lens projects the far sideline
    well outside the image, and only the part you can see should set the zoom.
    """
    poly = (calib or {}).get("court_polygon_px")
    if not poly:
        return None
    xs = [float(p[0]) for p in poly]
    width = min(max(xs), float(frame_w)) - max(min(xs), 0.0)
    return width if width > 0 else None


def crop_size(
    frame_w: int, frame_h: int, zoom: float, court_px_w: float | None = None
) -> tuple[float, float]:
    """16:9 follow-cam window in source pixels.

    `followcam.zoom` is a **divisor on the court's pixel width**: zoom = 4.5 frames
    about a fifth of the court, whatever the source resolution. A fixed fraction of the
    frame cannot work across the corpus — on a 2560x960 whole-court clip the old
    `frame_w / 2` left the subject ~60 px tall in an empty floor (samples/real/RESULTS.md).
    Without a calibration the court extent is unknown and the frame width stands in,
    which reproduces the old behaviour on a 16:9 source.
    """
    w = min(max((court_px_w or float(frame_w)) / max(zoom, 1e-3), MIN_CROP_W), float(frame_w))
    return w, min(w / CROP_ASPECT, float(frame_h))


def crop_path(
    boxes_px: np.ndarray,
    frame_w: int,
    frame_h: int,
    cfg: FollowCamCfg,
    *,
    fps: float = 30.0,
    court_px_w: float | None = None,
    dead_frac: float = DEAD_FRAC,
    vel_tau_s: float = VEL_TAU_S,
) -> np.ndarray:
    """(N, 4) boxes in pixels (NaN rows allowed) → (N, 4) normalised [x, y, w, h] rects."""
    n = len(boxes_px)
    cw, ch = crop_size(frame_w, frame_h, cfg.zoom, court_px_w)
    half = np.asarray([cw / 2.0, ch / 2.0])
    lo, hi = half, np.asarray([frame_w, frame_h]) - half
    if np.any(lo > hi):  # crop bigger than the frame
        lo = hi = np.asarray([frame_w / 2.0, frame_h / 2.0])

    if n == 0:
        return np.zeros((0, 4))
    # a track with no finite box at all would otherwise put NaN in the JSON
    targets = _targets(boxes_px)
    targets = np.where(np.isfinite(targets), targets, [frame_w / 2.0, frame_h / 2.0])

    dt = 1.0 / fps
    omega = max(cfg.stiffness, 1e-3)
    pos = np.clip(targets[0], lo, hi).astype(np.float64)
    vel = np.zeros(2)
    max_lead = np.asarray([cw, ch]) * MAX_LEAD_FRACTION
    band = np.asarray([cw, ch]) * dead_frac
    alpha = 1.0 - np.exp(-1.0 / (fps * vel_tau_s)) if vel_tau_s > 0 else 1.0
    held = targets[0].astype(np.float64).copy()
    motion = np.zeros(2)
    out = np.empty((n, 4))
    for i in range(n):
        if i:
            motion += alpha * ((targets[i] - targets[i - 1]) * fps - motion)
        d = targets[i] - held  # dead zone: only the part of a move beyond the band counts
        held += np.sign(d) * np.maximum(np.abs(d) - band, 0.0)
        lead = np.clip(motion * cfg.lead_s, -max_lead, max_lead)
        goal = np.clip(held + lead, lo, hi)
        # critically damped spring, semi-implicit Euler
        vel += (omega * omega * (goal - pos) - 2.0 * omega * vel) * dt
        pos = np.clip(pos + vel * dt, lo, hi)
        out[i] = [
            (pos[0] - cw / 2) / frame_w,
            (pos[1] - ch / 2) / frame_h,
            cw / frame_w,
            ch / frame_h,
        ]
    return np.clip(out, 0.0, 1.0)


def build_crop_path(
    player_id: str,
    boxes_px: np.ndarray,
    frame_w: int,
    frame_h: int,
    cfg: FollowCamCfg,
    *,
    rate_hz: int = 30,
    court_px_w: float | None = None,
) -> CropPath:
    rects = crop_path(boxes_px, frame_w, frame_h, cfg, fps=float(rate_hz), court_px_w=court_px_w)
    return CropPath(
        player_id=player_id,
        rate_hz=rate_hz,
        t0=0.0,
        rects=[tuple(round(float(v), 5) for v in r) for r in rects],
    )
