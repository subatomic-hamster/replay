"""Camera / floor geometry shared by the Tier D experiments (CPU, numpy only).

Conventions are the pipeline's (`calibration.json`, D-53): world = court metres, z up,
floor z = 0; x_cam = R x_world + t; pixels = K x_cam / z_cam (pinhole; both test clips
have k1 = 0, so no lens model here).
"""

from __future__ import annotations

import cv2
import numpy as np


def camera(cal: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    k, r, t = (np.asarray(cal[x], np.float64) for x in ("K", "R", "t"))
    if cal.get("dist") and abs(float(cal["dist"][0])) > 1e-9:
        raise ValueError("lens k1 != 0: these experiments assume a pinhole calibration")
    return k, r, t


def rays(k: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    """(H, W, 3) camera-frame rays (x/z, y/z, 1) through pixel centres."""
    w, h = size
    u, v = np.meshgrid(np.arange(w) + 0.5, np.arange(h) + 0.5)
    return np.stack([(u - k[0, 2]) / k[0, 0], (v - k[1, 2]) / k[1, 1], np.ones_like(u)], -1)


def floor_depth(k, r, t, size) -> np.ndarray:
    """(H, W) camera depth z at which each pixel's ray meets the floor z = 0 (NaN if never)."""
    c = -r.T @ t
    dz = rays(k, size) @ r[:, 2]  # world z component of each ray: (R^T ray)_z = ray . R[:, 2]
    with np.errstate(divide="ignore", invalid="ignore"):
        d = -c[2] / dz
    return np.where(d > 0, d, np.nan)


def to_world(u, v, d, k, r, t) -> np.ndarray:
    """(N, 3) world points of pixels (u, v) (pixel centres) at camera depth d."""
    x = np.stack([(u + 0.5 - k[0, 2]) / k[0, 0] * d, (v + 0.5 - k[1, 2]) / k[1, 1] * d, d], -1)
    return (x - t) @ r  # R^T (x - t), row-wise


def project(xyz, k, r, t) -> np.ndarray:
    x = np.asarray(xyz, np.float64).reshape(-1, 3) @ r.T + t
    return (x @ k.T)[:, :2] / x[:, 2:3]


def floor_region(k, r, t, size, polygon: np.ndarray, margin_m: float) -> np.ndarray:
    """(H, W) bool: pixels of the floor inside the court polygon grown by `margin_m`."""
    poly = np.asarray(polygon, np.float64)
    c = poly.mean(axis=0)
    grown = c + (poly - c) * (1 + margin_m / np.maximum(np.abs(poly - c), 1e-6))
    # densify so the polygon stays exact where it crosses the image border
    dense = np.vstack(
        [np.linspace(a, b, 50, endpoint=False) for a, b in zip(grown, np.roll(grown, -1, 0))]
    )
    xyz = np.column_stack([dense, np.zeros(len(dense))])
    front = (xyz @ r.T + t)[:, 2] > 0.1
    m = np.zeros((size[1], size[0]), np.uint8)
    cv2.fillPoly(m, [np.round(project(xyz[front], k, r, t)).astype(np.int32)], 1)
    return m.astype(bool) & np.isfinite(floor_depth(k, r, t, size))


def align_scale(d_pred: np.ndarray, d_floor: np.ndarray, sel: np.ndarray, k, r, t) -> dict:
    """Scale that maps predicted depth onto the calibrated floor (median ratio over `sel`)
    and the floor residuals after it: relative depth error and height above the plane."""
    sel = sel & np.isfinite(d_pred) & np.isfinite(d_floor) & (d_pred > 0)
    ratio = d_floor[sel] / d_pred[sel]
    s = float(np.median(ratio))
    rel = np.abs(s * d_pred[sel] - d_floor[sel]) / d_floor[sel]
    vs, us = np.nonzero(sel)
    z = to_world(us, vs, s * d_pred[sel], k, r, t)[:, 2]
    q = lambda a, p: float(np.percentile(a, p))
    return {
        "scale": s,
        "n_floor_px": int(sel.sum()),
        "rel_depth_err_med": q(rel, 50),
        "rel_depth_err_p90": q(rel, 90),
        "floor_abs_z_med_m": q(np.abs(z), 50),
        "floor_abs_z_p90_m": q(np.abs(z), 90),
    }


def _demo() -> None:
    """Self-check: a camera 3 m up looking down 30 deg; depth = floor depth * 0.8."""
    eye, tgt = np.array([0.0, -10.0, 3.0]), np.array([0.0, 0.0, 0.0])
    fwd = (tgt - eye) / np.linalg.norm(tgt - eye)
    right = np.cross(fwd, [0, 0, 1.0])
    right /= np.linalg.norm(right)
    r = np.vstack([right, np.cross(fwd, right), fwd])
    t = -r @ eye
    k = np.array([[500.0, 0, 320], [0, 500, 240], [0, 0, 1]])
    df = floor_depth(k, r, t, (640, 480))
    sel = floor_region(k, r, t, (640, 480), np.array([[-3, -3], [3, -3], [3, 3], [-3, 3.0]]), 0.0)
    assert sel.sum() > 1000
    vs, us = np.nonzero(sel)
    assert np.abs(to_world(us, vs, df[sel], k, r, t)[:, 2]).max() < 1e-9
    a = align_scale(df * 0.8, df, sel, k, r, t)
    assert abs(a["scale"] - 1.25) < 1e-9 and a["floor_abs_z_p90_m"] < 1e-9, a
    xyz = np.array([[1.0, 2.0, 1.5]])
    (pu, pv), z = project(xyz, k, r, t)[0], (xyz @ r.T + t)[0, 2]
    assert np.allclose(to_world(pu - 0.5, pv - 0.5, z, k, r, t), xyz)  # pixel centre = +0.5
    print("geom ok")  # ttsr-ignore: py/no-print (self-check entry point)


if __name__ == "__main__":
    _demo()
