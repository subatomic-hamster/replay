"""Virtual camera paths: one 16:9 window into the wide source per output frame.

A path is an (N, 3) array of window centre x, centre y and width in source pixels at the
render rate; the height is always width * 9/16. Every camera is a raw target (where an
operator would want to point) smoothed the way an operator moves a camera:

* a **dead zone** — small target moves do not move the camera at all;
* **anticipation** — the goal leads the target by its (smoothed) velocity;
* a **critically damped spring** — no overshoot, no snap, the same feel as courtcam's
  follow-cam (croppath) so the broadcast and the TV follow mode agree.

Zoom is smoothed in log space, so a 2x push-in feels the same at any focal length.
`jitter()` is the metric the evidence plots report.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

ASPECT = 16.0 / 9.0


@dataclass(frozen=True)
class Feel:
    """Operator feel for one camera. `omega` (rad/s) sets the spring's speed."""

    omega: float = 2.0
    zoom_omega: float = 1.2
    dead_frac: float = 0.06  # dead zone, as a fraction of the window width
    lead_s: float = 0.35  # anticipation
    vel_tau_s: float = 0.6  # EMA time constant of the velocity estimate used for the lead


WIDE_FEEL = Feel(omega=1.1, zoom_omega=0.8, dead_frac=0.10, lead_s=0.5)
TIGHT_FEEL = Feel(omega=1.8, zoom_omega=1.0, dead_frac=0.06, lead_s=0.4)
REPLAY_FEEL = Feel(omega=2.4, zoom_omega=1.5, dead_frac=0.04, lead_s=0.25)


def fit_window(
    cx: float,
    cy: float,
    w: float,
    frame_w: int,
    frame_h: int,
    min_w: float,
    aspect: float = ASPECT,
) -> tuple[float, float, float]:
    """Clamp a window to [min_w, the largest `aspect` (w/h, default 16:9) window the frame
    holds] and inside it."""
    w_max = min(float(frame_w), frame_h * aspect)
    w = float(np.clip(w, min(min_w, w_max), w_max))
    h = w / aspect
    cx = float(np.clip(cx, w / 2, frame_w - w / 2))
    cy = float(np.clip(cy, h / 2, frame_h - h / 2))
    return cx, cy, w


def _dead_zone(target: np.ndarray, widths: np.ndarray, frac: float) -> np.ndarray:
    """The goal only moves once the target leaves a band of `frac * width` around it."""
    out = np.empty_like(target)
    goal = target[0].copy()
    for i in range(len(target)):
        band = frac * widths[i]
        d = target[i] - goal
        goal = goal + np.sign(d) * np.maximum(np.abs(d) - band, 0.0)
        out[i] = goal
    return out


def _ema_velocity(x: np.ndarray, fps: float, tau_s: float) -> np.ndarray:
    a = 1.0 - np.exp(-1.0 / (fps * max(tau_s, 1e-3)))
    v = np.zeros_like(x)
    for i in range(1, len(x)):
        v[i] = v[i - 1] + a * ((x[i] - x[i - 1]) * fps - v[i - 1])
    return v


def spring(goal: np.ndarray, omega: float, fps: float, start: np.ndarray | None = None):
    """Critically damped spring chasing `goal` (N, D), semi-implicit Euler (as croppath)."""
    dt = 1.0 / fps
    pos = (goal[0] if start is None else start).astype(np.float64).copy()
    vel = np.zeros_like(pos)
    out = np.empty_like(goal, dtype=np.float64)
    for i in range(len(goal)):
        vel += (omega * omega * (goal[i] - pos) - 2.0 * omega * vel) * dt
        pos = pos + vel * dt
        out[i] = pos
    return out


def smooth(
    raw: np.ndarray,
    feel: Feel,
    fps: float,
    frame_w: int,
    frame_h: int,
    min_w: float,
    aspect: float = ASPECT,
) -> np.ndarray:
    """Raw (N, 3) [cx, cy, w] targets -> an operator-smooth, frame-clamped path (windows
    of `aspect` = w/h; 9/16 for the vertical share export)."""
    if len(raw) == 0:
        return raw.copy()
    raw = raw.astype(np.float64)
    logw = spring(np.log(raw[:, 2:3]), feel.zoom_omega, fps)[:, 0]
    w = np.exp(logw)
    xy = _dead_zone(raw[:, :2], w[:, None], feel.dead_frac)
    lead = _ema_velocity(xy, fps, feel.vel_tau_s) * feel.lead_s
    lead = np.clip(lead, -0.25 * w[:, None], 0.25 * w[:, None])
    xy = spring(xy + lead, feel.omega, fps)
    out = np.column_stack([xy, w])
    for i in range(len(out)):
        out[i] = fit_window(*out[i], frame_w, frame_h, min_w, aspect)
    return out


def ease(u: np.ndarray | float) -> np.ndarray | float:
    """Smootherstep: zero velocity and acceleration at both ends."""
    u = np.clip(u, 0.0, 1.0)
    return u * u * u * (u * (u * 6 - 15) + 10)


def blend(a: np.ndarray, b: np.ndarray, u: float) -> np.ndarray:
    """Window between `a` and `b` (u in 0..1); width interpolated in log space."""
    k = float(ease(u))
    return np.array(
        [
            a[0] + (b[0] - a[0]) * k,
            a[1] + (b[1] - a[1]) * k,
            float(np.exp(np.log(a[2]) + (np.log(b[2]) - np.log(a[2])) * k)),
        ]
    )


def jitter(path: np.ndarray, out_w: float = 1920.0) -> dict[str, float]:
    """Screen-space shake: second difference of the window centre in OUTPUT pixels per
    frame^2 (a still camera scores 0), plus the zoom's relative second difference."""
    if len(path) < 3:
        return {"rms_px": 0.0, "p95_px": 0.0, "zoom_rms": 0.0}
    scale = out_w / path[1:-1, 2]
    acc = np.linalg.norm(np.diff(path[:, :2], 2, axis=0), axis=1) * scale
    zacc = np.abs(np.diff(np.log(path[:, 2]), 2))
    return {
        "rms_px": round(float(np.sqrt(np.mean(acc**2))), 4),
        "p95_px": round(float(np.percentile(acc, 95)), 4),
        "zoom_rms": round(float(np.sqrt(np.mean(zacc**2))), 6),
    }


def rect_norm(win: np.ndarray, frame_w: int, frame_h: int) -> tuple[float, float, float, float]:
    """[cx, cy, w] -> normalised [x, y, w, h] (the crops.json convention)."""
    cx, cy, w = (float(v) for v in win)
    h = w / ASPECT
    return ((cx - w / 2) / frame_w, (cy - h / 2) / frame_h, w / frame_w, h / frame_h)


def from_rect_norm(r, frame_w: int, frame_h: int) -> np.ndarray:
    x, y, w, h = r
    return np.array([(x + w / 2) * frame_w, (y + h / 2) * frame_h, w * frame_w])
