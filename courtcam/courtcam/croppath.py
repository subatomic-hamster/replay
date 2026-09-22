"""Stage 8 — per-player follow-cam crop paths (plan §4.4 step 8).

One rect per video frame at 30 Hz, normalised to [0, 1], `t0 = 0`. The camera is a
critically damped spring chasing the player's box centre plus a short motion lead,
clamped inside the frame. Through a tracking gap the target holds still, so the
window parks and eases back when the player reappears.
"""

from __future__ import annotations

import numpy as np

from .profiles import FollowCamCfg
from .schema import CropPath

MAX_LEAD_FRACTION = 0.25  # of the crop window, so a sprint cannot throw the frame


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


def crop_size(frame_w: int, frame_h: int, zoom: float) -> tuple[float, float]:
    # ponytail: constant zoom from the profile. 2.0 suits a tight source; on a 2560-px
    # whole-court clip the subject comes out ~60 px tall in a frame of empty floor. It
    # wants to scale with the court's pixel width (calib.court_polygon_px) once some
    # clip actually needs both.
    return frame_w / zoom, frame_h / zoom


def crop_path(
    boxes_px: np.ndarray,
    frame_w: int,
    frame_h: int,
    cfg: FollowCamCfg,
    *,
    fps: float = 30.0,
) -> np.ndarray:
    """(N, 4) boxes in pixels (NaN rows allowed) → (N, 4) normalised [x, y, w, h] rects."""
    n = len(boxes_px)
    cw, ch = crop_size(frame_w, frame_h, cfg.zoom)
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
    out = np.empty((n, 4))
    for i in range(n):
        motion = (targets[i] - targets[i - 1]) * fps if i else np.zeros(2)
        lead = np.clip(motion * cfg.lead_s, -max_lead, max_lead)
        goal = np.clip(targets[i] + lead, lo, hi)
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
) -> CropPath:
    rects = crop_path(boxes_px, frame_w, frame_h, cfg, fps=float(rate_hz))
    return CropPath(
        player_id=player_id,
        rate_hz=rate_hz,
        t0=0.0,
        rects=[tuple(round(float(v), 5) for v in r) for r in rects],
    )
