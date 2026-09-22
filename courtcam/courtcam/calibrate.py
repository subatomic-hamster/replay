"""Stage 2 — pixel→court homography from landmark clicks (plan §4.4 step 2)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .profiles import CourtTemplate, Profile

MAX_REPROJ_PX = 5.0
# ...and, on a bigger frame, 1 % of how wide the clicked court is. 5 px is a sane floor
# for a 720p clip but an impossible bar on a 2560-px panorama: the fit there is barrel
# distorted (D-18) *and* a tap is worth several source pixels, so a hand-clicked set
# lands at 10-20 px however carefully it is placed, while the court polygon it yields is
# still well inside `margin_m` of the right one. Measured in samples/real/RESULTS.md.
MAX_REPROJ_SPAN_FRAC = 0.01
# RANSAC's threshold is in the units of the *destination* points. Fitting pixels->metres
# meant a "3.0" that stood for three court metres, so it never rejected anything; the fit
# runs metres->pixels instead and 4 px is a real bar. Below this many points every click
# is needed to pin the homography down, so there is nothing to vote out: plain least
# squares, and a bad click shows up as a big residual on every point.
MAX_RANSAC_PX = 4.0
RANSAC_MIN_POINTS = 6


class CalibrationError(ValueError):
    """Landmarks did not produce a usable homography."""


def homography(
    landmarks_px: dict[str, tuple[float, float]], template: CourtTemplate
) -> tuple[np.ndarray, dict[str, float]]:
    """Return (H pixels→metres, per-landmark reprojection error in px)."""
    names = [n for n in landmarks_px if n in template.landmarks]
    if len(names) < 4:
        raise CalibrationError(
            f"need >= 4 landmarks known to template {template.name}, got {sorted(names)}"
        )
    src = np.asarray([landmarks_px[n] for n in names], dtype=np.float64)
    dst = template.landmark_array(names)
    # The fit below runs metres->pixels, and OpenCV only rejects a degenerate *source*
    # set — which is the template's metres, never degenerate. So check the clicks here:
    # if they all sit on one line there is no homography, whatever the residuals say.
    spread = np.linalg.svd(src - src.mean(axis=0), compute_uv=False)
    if spread[0] <= 0.0 or spread[1] / spread[0] < 1e-3:
        raise CalibrationError("landmark clicks are collinear — no homography")
    # ponytail: plain homography, no lens model. Wide/panoramic gym cameras are barrel
    # distorted, so the fit contains the play area but does not sit on the lines and the
    # reprojection error flatters it (see samples/real/RESULTS.md). Good enough for the
    # on-court filter, not for court-metre analytics; cv2.calibrateCamera with k1,k2
    # estimated from the straight court lines is the upgrade.
    # float64 throughout: getPerspectiveTransform is float32 and loses ~1e-4 px.
    # Fit metres->pixels so RANSAC's threshold is in pixels, then invert.
    h_inv, _ = (
        cv2.findHomography(dst, src, cv2.RANSAC, MAX_RANSAC_PX)
        if len(names) >= RANSAC_MIN_POINTS
        else cv2.findHomography(dst, src)
    )
    if h_inv is None:
        raise CalibrationError("findHomography failed (degenerate landmark configuration)")
    h_inv = np.asarray(h_inv, dtype=np.float64)
    try:
        h = np.linalg.inv(h_inv)
    except np.linalg.LinAlgError as exc:
        raise CalibrationError(f"homography is not invertible ({exc})") from exc
    errs = np.linalg.norm(project(dst, h_inv) - src, axis=1)
    return h, {n: float(e) for n, e in zip(names, errs, strict=True)}


def fit_error_px(residuals: dict[str, float]) -> float:
    """The fit's own error: the worst residual among the points RANSAC kept.

    A click further out than `MAX_RANSAC_PX` was voted out of the fit, so folding it into
    the number would report the user's mistake as the homography's. It still rides along
    in `residuals_px` so the UI can point at it. If fewer than 4 points survive there was
    no consensus to speak of and the worst residual is the honest answer.
    """
    kept = [r for r in residuals.values() if r <= MAX_RANSAC_PX]
    return max(kept) if len(kept) >= 4 else max(residuals.values())


def project(points: np.ndarray, h: np.ndarray) -> np.ndarray:
    """Apply a homography to an (N, 2) array."""
    pts = np.asarray(points, dtype=np.float64).reshape(-1, 1, 2)
    return cv2.perspectiveTransform(pts, h).reshape(-1, 2)


def max_reproj_px(
    landmarks_px: dict[str, tuple[float, float]], floor_px: float = MAX_REPROJ_PX
) -> float:
    """The gate for this click set: `floor_px`, or 1 % of how far the clicks spread."""
    pts = list(landmarks_px.values())
    if not pts:
        return floor_px
    span = max(
        max(p[0] for p in pts) - min(p[0] for p in pts),
        max(p[1] for p in pts) - min(p[1] for p in pts),
    )
    return max(floor_px, MAX_REPROJ_SPAN_FRAC * span)


def calibrate(
    landmarks_px: dict[str, tuple[float, float]],
    profile: Profile,
    variant: str | None = None,
    *,
    max_error_px: float = MAX_REPROJ_PX,
) -> dict[str, Any]:
    """Build the `calib.json` payload. Raises `CalibrationError` if reprojection is poor.

    `max_error_px` is the *floor* of the gate; see `max_reproj_px`.
    """
    variant = variant or profile.default_variant()
    template = profile.template(variant)
    h, residuals = homography(landmarks_px, template)
    err = fit_error_px(residuals)
    limit = max_reproj_px(landmarks_px, max_error_px)
    if err > limit:
        raise CalibrationError(
            f"reprojection error {err:.2f} px > {limit:.1f} px — re-click the landmarks"
        )
    h_inv = np.linalg.inv(h)
    return {
        "schema": "courtcam.calib.v1",
        "sport": profile.id,
        "variant": variant,
        "standard": template.standard,
        "landmarks_px": {k: [float(v[0]), float(v[1])] for k, v in landmarks_px.items()},
        "H": h.tolist(),
        "H_inv": h_inv.tolist(),
        "reproj_error_px": err,
        # Per-landmark, so the uploader can highlight the click that is off (bug 3).
        "residuals_px": {k: round(v, 3) for k, v in residuals.items()},
        "court_polygon_m": template.polygon.tolist(),
        "court_polygon_px": project(template.polygon, h_inv).tolist(),
        "rim_m": list(template.rim) if template.rim else None,
        "rim_px": project(np.asarray([template.rim]), h_inv)[0].tolist() if template.rim else None,
    }


def write_calib(path: Path, calib: dict[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(calib, indent=1), encoding="utf-8")
    return path


def read_calib(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))
