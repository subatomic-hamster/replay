"""Lens distortion — one-parameter division model about the image centre (D-24).

D-22 said: no distortion model until a clip fails the reprojection gate with residuals
that *grow with radius from the image centre*. `badminton_auditorium_240s.mp4` is that
clip — 4 px of residual inside r = 330 px, 17–42 px beyond r = 440 px — so this is the
smallest thing that fixes it.

Fitzgibbon's division model, one parameter, radius normalised by half the image diagonal:

    r_undistorted = r_distorted / (1 + k1 · r_distorted²)

Barrel distortion (every ultra-wide lens) gives `k1 < 0`. One parameter, not two: `k2`
buys nothing on a 12-landmark fit, and the inverse — needed to draw a court line back
onto the frame — is closed form only for the one-parameter form.

`k1` is estimated from the landmarks themselves: the value that makes a single
homography sit on all of them at once. It is gated (`MIN_POINTS`, `MIN_GAIN`) so a
well-behaved 1× lens keeps `k1 = 0` and the old code path exactly.
"""

from __future__ import annotations

import cv2
import numpy as np

MIN_POINTS = 8
"""Below this a homography barely has slack for a 9th unknown; `k1` would absorb clicks."""
MIN_GAIN = 0.30
"""`k1` ships only if it cuts the reprojection RMS by this much. Otherwise it is noise."""
K1_RANGE = (-0.80, 0.20)
"""Grid searched. -0.8 is far past any real lens; +0.2 leaves room for pincushion."""
GRID = 81


def _centre_scale(image_size: tuple[int, int]) -> tuple[np.ndarray, float]:
    w, h = image_size
    return np.asarray([w / 2.0, h / 2.0], dtype=np.float64), 0.5 * float(np.hypot(w, h))


def undistort_points(pts, k1: float, image_size: tuple[int, int]) -> np.ndarray:
    """Distorted pixels → ideal pinhole pixels. `k1 == 0` is the identity."""
    pts = np.asarray(pts, dtype=np.float64).reshape(-1, 2)
    if not k1:
        return pts.copy()
    c, s = _centre_scale(image_size)
    d = (pts - c) / s
    r2 = (d**2).sum(axis=1, keepdims=True)
    return c + s * d / (1.0 + k1 * r2)


def distort_points(pts, k1: float, image_size: tuple[int, int]) -> np.ndarray:
    """Ideal pinhole pixels → distorted pixels; the exact inverse of `undistort_points`.

    `r_u = r_d / (1 + k1 r_d²)` is a quadratic in `r_d`, so the inverse is closed form.
    Written as `2 / (1 + sqrt(1 - 4 k1 r_u²))` rather than the textbook
    `(1 - sqrt(…)) / (2 k1 r_u²)`: same value, no cancellation as `k1 → 0`, no division
    by zero at the centre.
    """
    pts = np.asarray(pts, dtype=np.float64).reshape(-1, 2)
    if not k1:
        return pts.copy()
    c, s = _centre_scale(image_size)
    u = (pts - c) / s
    r2 = (u**2).sum(axis=1, keepdims=True)
    scale = 2.0 / (1.0 + np.sqrt(np.maximum(1.0 - 4.0 * k1 * r2, 0.0)))
    return c + s * u * scale


def reprojection_rms(
    landmarks_px: np.ndarray, template_pts: np.ndarray, k1: float, image_size: tuple[int, int]
) -> float:
    """RMS reprojection error **in distorted pixels** of the homography fit at `k1`.

    Measured after re-distorting, not in undistorted space: undistorting shrinks the
    whole image, so an undistorted-space error would fall for free as `|k1|` grows and
    the search would run away to the edge of `K1_RANGE`.
    """
    und = undistort_points(landmarks_px, k1, image_size)
    h_inv, _ = cv2.findHomography(template_pts, und)
    if h_inv is None:
        return float("inf")
    back = cv2.perspectiveTransform(
        template_pts.reshape(-1, 1, 2).astype(np.float64), h_inv
    ).reshape(-1, 2)
    err = np.linalg.norm(distort_points(back, k1, image_size) - landmarks_px, axis=1)
    return float(np.sqrt((err**2).mean()))


def _golden(f, lo: float, hi: float, tol: float = 1e-4) -> float:
    """Golden-section minimum of a unimodal `f` on [lo, hi]. No scipy in this package."""
    phi = (np.sqrt(5.0) - 1.0) / 2.0
    a, b = lo, hi
    c, d = b - phi * (b - a), a + phi * (b - a)
    fc, fd = f(c), f(d)
    while b - a > tol:
        if fc < fd:
            b, d, fd = d, c, fc
            c = b - phi * (b - a)
            fc = f(c)
        else:
            a, c, fc = c, d, fd
            d = a + phi * (b - a)
            fd = f(d)
    return (a + b) / 2.0


def estimate_k1(
    landmarks_px, template_pts, image_size: tuple[int, int]
) -> tuple[float, float, float]:
    """`(k1, rms before, rms after)` — grid search then golden-section refine.

    Returns `k1 = 0.0` (and equal errors) unless there are at least `MIN_POINTS`
    landmarks *and* the fit improves by `MIN_GAIN`. A 1× lens therefore lands on the
    plain homography, byte for byte.
    """
    landmarks_px = np.asarray(landmarks_px, dtype=np.float64).reshape(-1, 2)
    template_pts = np.asarray(template_pts, dtype=np.float64).reshape(-1, 2)
    base = reprojection_rms(landmarks_px, template_pts, 0.0, image_size)
    if len(landmarks_px) < MIN_POINTS or not np.isfinite(base):
        return 0.0, base, base

    def cost(k: float) -> float:
        return reprojection_rms(landmarks_px, template_pts, float(k), image_size)

    grid = np.linspace(*K1_RANGE, GRID)
    costs = [cost(k) for k in grid]
    i = int(np.argmin(costs))
    lo, hi = grid[max(i - 1, 0)], grid[min(i + 1, GRID - 1)]
    k1 = _golden(cost, float(lo), float(hi))
    err = cost(k1)
    if not np.isfinite(err) or err > (1.0 - MIN_GAIN) * base:
        return 0.0, base, base
    return float(k1), base, float(err)
