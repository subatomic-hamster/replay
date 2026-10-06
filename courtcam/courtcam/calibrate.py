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
    if len(names) >= RANSAC_MIN_POINTS:
        # Deterministic: cv2.theRNG() is process-global, so the same clicks used to
        # calibrate differently run to run (measured on the badminton auditorium clip:
        # 1.3-2.5 px reported, 26-90 px worst, a different consensus each time).
        cv2.setRNGSeed(0)
        h_inv, mask = cv2.findHomography(dst, src, cv2.RANSAC, MAX_RANSAC_PX)
        # RANSAC is a vote against a couple of bad clicks, not a licence to fit five of
        # twelve points and report *that* error. On a barrel-distorted frame the pinhole
        # model genuinely cannot hold all the landmarks, so RANSAC finds a small
        # consensus and reports 1.5 px for a fit whose worst landmark is 167 px out
        # (samples/real/RESULTS.md). Once more than two points are voted out there is no
        # consensus worth the name: refit by least squares over everything and let the
        # residuals say so.
        if h_inv is None or mask is None or int(mask.sum()) < len(names) - 2:
            h_inv, _ = cv2.findHomography(dst, src)
    else:
        h_inv, _ = cv2.findHomography(dst, src)
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
    in `residuals_px` so the UI can point at it. Excusing a point is capped at 2 — the
    same bar `homography` uses to keep a RANSAC consensus at all — so a least-squares
    fallback over a frame the pinhole model cannot hold reports its worst landmark
    instead of the handful it happens to sit on.
    """
    kept = [r for r in residuals.values() if r <= MAX_RANSAC_PX]
    excused = len(residuals) - len(kept)
    return max(kept) if len(kept) >= 4 and excused <= 2 else max(residuals.values())


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


# --- full camera calibration (M8): K, R, t from the court homography + height landmarks ---

RIM_HEIGHT_M = 3.05
CALIBRATION_SCHEMA = "replay.calibration.v1"
DIST_MODEL = "division_k1_about_image_centre (courtcam.distortion)"


def height_landmarks(template: CourtTemplate) -> dict[str, tuple[float, float, float]]:
    """Optional off-floor landmarks a user can click for the PnP refinement, in metres.

    `rim_top` is the centre of the near hoop (the floor point under it is the template's
    `rim`); `rim_top_f` the far one on a full court; `net_top_l` / `net_top_r` are the
    tops of the net posts (the net's top edge where it meets each sideline), at the
    template's `net_height_m`. Derived from the template, so no profile needs editing.
    """
    out: dict[str, tuple[float, float, float]] = {}
    rims = list(template.rims) or ([template.rim] if template.rim else [])
    for name, rim in zip(("rim_top", "rim_top_f"), rims, strict=False):
        out[name] = (float(rim[0]), float(rim[1]), RIM_HEIGHT_M)
    net_h = (template.model_extra or {}).get("net_height_m")
    if template.net_y is not None and net_h:
        half_w = template.size[0] / 2.0
        for side, x in (("l", -half_w), ("r", half_w)):
            px, py = template.landmarks.get(f"net_post_{side}", (x, template.net_y))
            out[f"net_top_{side}"] = (float(px), float(py), float(net_h))
    return out


def world_landmarks(template: CourtTemplate) -> dict[str, tuple[float, float, float]]:
    """Every landmark the template knows, floor ones at z = 0, in metres (z up)."""
    floor = {k: (float(v[0]), float(v[1]), 0.0) for k, v in template.landmarks.items()}
    return {**floor, **height_landmarks(template)}


def focal_from_homography(h_inv: np.ndarray, size: tuple[int, int]) -> float | None:
    """Focal length (px) of a camera with square pixels and the principal point at the
    image centre that makes the court homography `h_inv` (metres -> undistorted px).

    With K = diag(f, f, 1) about the centre, the first two columns of K^-1 H are the
    court's x and y axes in camera space: orthogonal and of equal length (Zhang's two
    constraints, here with one unknown w = 1/f^2). Least squares over both; None when
    neither constrains f (e.g. a camera looking straight down the court's axes).
    """
    w, h = size
    centre = np.array([[1.0, 0.0, -w / 2.0], [0.0, 1.0, -h / 2.0], [0.0, 0.0, 1.0]])
    g = centre @ np.asarray(h_inv, dtype=np.float64)
    g = g / np.linalg.norm(g[:, :2])
    c1, c2 = g[:, 0], g[:, 1]
    a = np.array([c1[0] * c2[0] + c1[1] * c2[1], c1[0] ** 2 + c1[1] ** 2 - c2[0] ** 2 - c2[1] ** 2])
    b = np.array([c1[2] * c2[2], c1[2] ** 2 - c2[2] ** 2])
    denom = float(a @ a)
    if denom < 1e-18:
        return None
    inv_f2 = -float(a @ b) / denom
    if inv_f2 <= 0:
        return None
    return float(1.0 / np.sqrt(inv_f2))


def _k(f: float, size: tuple[int, int]) -> np.ndarray:
    return np.array([[f, 0.0, size[0] / 2.0], [0.0, f, size[1] / 2.0], [0.0, 0.0, 1.0]])


def pose_from_homography(h_inv: np.ndarray, k: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(R, t) world -> camera from a floor homography (metres -> px) and intrinsics K.

    K^-1 H = s [r1 r2 t]; s is fixed by |r1| = |r2| = 1 on average and its sign by the
    court lying in front of the camera; r1, r2 are made orthonormal (polar decomposition).
    """
    m = np.linalg.inv(k) @ np.asarray(h_inv, dtype=np.float64)
    lam = 2.0 / (np.linalg.norm(m[:, 0]) + np.linalg.norm(m[:, 1]))
    if m[2, 2] < 0:  # the court origin must have positive depth
        lam = -lam
    m = m * lam
    u, _, vt = np.linalg.svd(m[:, :2], full_matrices=False)
    r12 = u @ vt
    r = np.column_stack([r12[:, 0], r12[:, 1], np.cross(r12[:, 0], r12[:, 1])])
    return r, m[:, 2].copy()


def _pnp(
    world: np.ndarray, px: np.ndarray, k: np.ndarray, r0: np.ndarray, t0: np.ndarray
) -> tuple[np.ndarray, np.ndarray, float]:
    """Levenberg-Marquardt PnP from (r0, t0); returns R, t and RMS in undistorted px."""
    rvec, _ = cv2.Rodrigues(r0)
    tvec = t0.reshape(3, 1).copy()
    ok, rvec, tvec = cv2.solvePnP(
        world, px, k, None, rvec, tvec, useExtrinsicGuess=True, flags=cv2.SOLVEPNP_ITERATIVE
    )
    if not ok:
        rvec, tvec = cv2.Rodrigues(r0)[0], t0.reshape(3, 1)
    proj, _ = cv2.projectPoints(world, rvec, tvec, k, None)
    rms = float(np.sqrt(((proj.reshape(-1, 2) - px) ** 2).sum(axis=1).mean()))
    return cv2.Rodrigues(rvec)[0], tvec.reshape(3), rms


def camera_calibration(
    calib: dict[str, Any],
    profile: Profile,
    landmarks_px: dict[str, tuple[float, float]] | None = None,
) -> dict[str, Any]:
    """`calibration.json` (replay.calibration.v1) from a `calib.json` payload.

    1. f from the court homography (`focal_from_homography`; square pixels, principal
       point at the image centre — the distortion centre of D-25's `k1`);
    2. R, t by decomposing the homography at that f;
    3. PnP refinement over every clicked landmark, floor and height ones (rim 3.05 m,
       net-post tops), with f re-searched (golden section on log f) to minimise the
       reprojection RMS. Height landmarks are what make f and the camera height
       observable beyond the floor homography; without them step 3 only polishes.

    `landmarks_px` defaults to the clicks stored in `calib` (floor and height names from
    `world_landmarks`; unknown names are ignored). Pixels are undistorted with
    `calib["k1"]` before fitting; `reproj_err_px` and `residuals_px` are measured back in
    source pixels.
    """
    from . import distortion

    template = profile.template(calib.get("variant"))
    world = world_landmarks(template)
    clicks = landmarks_px if landmarks_px is not None else calib.get("landmarks_px", {})
    names = [n for n in clicks if n in world]
    size = tuple(int(v) for v in calib.get("image_size") or ())
    if len(size) != 2:
        raise CalibrationError("calib.json has no image_size; re-run calibrate")
    k1 = float(calib.get("k1") or 0.0)
    src = np.asarray([clicks[n] for n in names], dtype=np.float64)
    und = distortion.undistort_points(src, k1, size)
    obj = np.asarray([world[n] for n in names], dtype=np.float64)
    heights = [n for n in names if world[n][2] != 0.0]

    h_inv = np.asarray(calib["H_inv"], dtype=np.float64)
    f0 = focal_from_homography(h_inv, size)
    focal_source = "homography"
    if f0 is None:
        f0 = float(size[0])  # ~53 deg HFOV: only a starting point for the search
        focal_source = "default"
    # A camera must stand above the floor. If the only camera that explains the clicks is
    # below it, the user's l/r (or n/f) labelling is the mirror image of the template's
    # right-handed axes — legal for a 2D homography, not for 3D. Fit in the mirrored
    # world (x -> -x, a proper rotation there) and fold the mirror into R, which is then
    # improper (det -1): P = K [R | t] still maps the template's own coordinates, so every
    # consumer keeps using court metres as tracked. `mirrored` says so.
    mirror = np.diag([1.0, 1.0, 1.0])
    r0, t0 = pose_from_homography(h_inv, _k(f0, size))
    if (-r0.T @ t0)[2] < 0:
        mirror = np.diag([-1.0, 1.0, 1.0])
    h_fit, obj_fit = h_inv @ mirror, obj @ mirror
    r0, t0 = pose_from_homography(h_fit, _k(f0, size))

    def fit(f: float) -> tuple[np.ndarray, np.ndarray, float]:
        r_h, t_h = pose_from_homography(h_fit, _k(f, size))
        return _pnp(obj_fit, und, _k(f, size), r_h, t_h)

    if len(names) >= 4:
        lo, hi = np.log(0.5 * f0), np.log(2.0 * f0)
        log_f = distortion._golden(lambda x: fit(float(np.exp(x)))[2], lo, hi, tol=1e-4)
        f = float(np.exp(log_f))
        r, t, _ = fit(f)
        focal_source += "+pnp_heights" if heights else "+pnp"
    else:
        f, r, t = f0, r0, t0
    k = _k(f, size)
    proj, _ = cv2.projectPoints(obj_fit, cv2.Rodrigues(r)[0], t, k, None)
    r = r @ mirror
    back = distortion.distort_points(proj.reshape(-1, 2), k1, size)
    errs = np.linalg.norm(back - src, axis=1)
    return {
        "schema": CALIBRATION_SCHEMA,
        "sport": profile.id,
        "variant": calib.get("variant"),
        "image_size": list(size),
        # pixels (undistorted) -> metres, as in calib.json; `H_inv` the other way
        "H": np.asarray(calib["H"], dtype=np.float64).tolist(),
        "H_inv": h_inv.tolist(),
        "K": k.tolist(),
        "R": r.tolist(),
        "t": t.tolist(),
        "dist": [k1],
        "dist_model": DIST_MODEL,
        "reproj_err_px": round(float(np.sqrt((errs**2).mean())), 3) if len(errs) else None,
        "residuals_px": {n: round(float(e), 3) for n, e in zip(names, errs, strict=True)},
        "landmarks_px": {n: [float(clicks[n][0]), float(clicks[n][1])] for n in names},
        "landmarks_world": {n: list(world[n]) for n in names},
        "height_landmarks": heights,
        "focal_px": round(f, 3),
        "focal_source": focal_source,
        "camera_position_m": (-r.T @ t).tolist(),
        "mirrored": bool(mirror[0, 0] < 0),
    }


def camera_matrix(calibration: dict[str, Any]) -> np.ndarray:
    """3x4 P = K [R | t] (world metres, z up -> undistorted pixels)."""
    k, r = np.asarray(calibration["K"]), np.asarray(calibration["R"])
    return k @ np.column_stack([r, np.asarray(calibration["t"])])


def write_calib(path: Path, calib: dict[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(calib, indent=1), encoding="utf-8")
    return path


def read_calib(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))
