"""2D keypoints + full calibration -> 3D joints in court metres (z up).

Two placement paths, same output:

* `place_lifted` (MotionBERT extra): each frame's keypoints are re-projected into a
  virtual camera that looks straight at the player (a pure rotation of the real camera,
  so wide-angle perspective off the image centre does not bend the pose) and scaled by
  the player's distance to roughly metres-at-the-player, the shape MotionBERT saw in
  training. Its root-relative 3D comes back in that virtual camera's axes, is rotated
  into the court frame per frame, levelled (the median spine is made vertical, at most
  25°: H36M cameras sit at chest height, ours look down), scaled to the player's height
  and translated so the ankles land on their measured floor points.
* `place_analytic` (licence-clean fallback): ankles where their rays meet the floor,
  pelvis on its ray above them, every other joint on its ray in the plane through the
  pelvis facing the camera, then each bone given its anthropometric length by moving
  the child along the line of sight (limbs toward the facing direction, left/right
  joints to their side) — Taylor's method with fixed bone lengths.

The player's height comes from the calibration: the eyes' ray above the tracked foot
point gives the eye height (median over the window, / 0.936, clamped to 1.6-2.1 m).
"""

from __future__ import annotations

import numpy as np

from courtcam import distortion

from .motion import _ik_knee, savgol
from .skeleton import (
    ANKLE_H_M,
    ANKLES,
    BONES,
    EYE_FRAC,
    HEAD,
    HIPS,
    KNEES,
    PELVIS,
    PELVIS_FRAC,
    SHOULDERS,
    THORAX,
    bone_lengths,
    stature,
)

UNIT_PER_M = 0.458  # H36M: a 1.7 m subject ~5 m from a f = 1145 px camera spans ~0.78 units
MIN_CONF = 0.2
MAX_TILT_DEG = 25.0
EZ = np.array([0.0, 0.0, 1.0])
# analytic placement: per child joint, the prior bone direction as (up, forward, right)
# weights; of the two points on the child's ray at the bone's length, the one that
# better agrees with it wins (knees and elbows a little forward, forearms forward)
PRIOR = {
    1: (0, 0, 1), 4: (0, 0, -1), 2: (-1, 0.25, 0), 5: (-1, 0.25, 0), 3: (-1, 0, 0),
    6: (-1, 0, 0), 7: (1, 0, 0), 8: (1, 0, 0), 9: (1, 0.6, 0), 10: (1, 0, 0),
    14: (0, 0, 1), 11: (0, 0, -1), 15: (-1, 0.3, 0), 12: (-1, 0.3, 0), 16: (-0.3, 1, 0),
    13: (-0.3, 1, 0),
}  # fmt: skip


class Camera:
    """The real camera: K, R, t (world -> camera, x right, y down) + division-model k1."""

    def __init__(self, k, r, t, k1: float = 0.0, size: tuple[int, int] = (1920, 1080)):
        self.k = np.asarray(k, np.float64)
        self.r = np.asarray(r, np.float64)
        self.t = np.asarray(t, np.float64).reshape(3)
        self.k1, self.size = float(k1), (int(size[0]), int(size[1]))
        self.centre = -self.r.T @ self.t
        self.k_inv = np.linalg.inv(self.k)

    @classmethod
    def from_calibration(cls, cal: dict) -> Camera:
        dist = cal.get("dist") or [0.0]
        return cls(cal["K"], cal["R"], cal["t"], float(dist[0]), tuple(cal["image_size"]))

    def cam_rays(self, px: np.ndarray) -> np.ndarray:
        """(..., 2) distorted pixels -> (..., 3) camera-frame directions (z = 1)."""
        flat = np.asarray(px, np.float64).reshape(-1, 2)
        ok = np.isfinite(flat).all(axis=1)
        und = np.full_like(flat, np.nan)
        if ok.any():
            und[ok] = distortion.undistort_points(flat[ok], self.k1, self.size)
        h = np.column_stack([und, np.ones(len(und))]) @ self.k_inv.T
        return h.reshape((*np.shape(px)[:-1], 3))

    def rays(self, px: np.ndarray) -> np.ndarray:
        """(..., 2) pixels -> (..., 3) unit world directions from the camera centre."""
        d = self.cam_rays(px) @ self.r
        return d / np.linalg.norm(d, axis=-1, keepdims=True)

    def project(self, xyz: np.ndarray) -> np.ndarray:
        c = np.asarray(xyz, np.float64).reshape(-1, 3) @ self.r.T + self.t
        p = c @ self.k.T
        und = p[:, :2] / p[:, 2:3]
        return distortion.distort_points(und, self.k1, self.size) if self.k1 else und


def _nanmean(a: np.ndarray, axis: int) -> np.ndarray:
    """np.nanmean without the empty-slice warning (all-NaN -> NaN)."""
    ok = np.isfinite(a)
    n = ok.sum(axis=axis)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(ok, a, 0.0).sum(axis=axis) / np.where(n > 0, n, np.nan)


def floor_hit(c: np.ndarray, d: np.ndarray, z: float) -> np.ndarray:
    """Where rays c + s d meet the plane at height z; NaN for rays that do not."""
    s = (z - c[2]) / d[..., 2]
    p = c + s[..., None] * d
    p[~(s > 0)] = np.nan
    return p


def above(c: np.ndarray, d: np.ndarray, xy: np.ndarray) -> np.ndarray:
    """Point of each ray c + s d closest to the vertical line through xy."""
    dh = d[..., :2]
    s = np.sum((xy - c[:2]) * dh, axis=-1) / np.maximum(np.sum(dh * dh, axis=-1), 1e-12)
    return c + s[..., None] * d


def fill_keypoints(kp: np.ndarray) -> np.ndarray:
    """(F, 17, 3) pixels + score: low-score joints interpolated in time inside frames
    where the player has any keypoint; frames with none stay NaN."""
    out = kp.copy()
    present = (kp[..., 2] >= MIN_CONF).any(axis=1)
    idx = np.arange(len(kp))
    for j in range(kp.shape[1]):
        ok = present & (kp[:, j, 2] >= MIN_CONF) & np.isfinite(kp[:, j, 0])
        if ok.sum() == 0:
            out[present, j] = np.nan
            continue
        for c in range(2):
            out[:, j, c] = np.interp(idx, idx[ok], kp[ok, j, c])
        out[present & ~ok, j, 2] = MIN_CONF
    out[~present] = np.nan
    return out


def player_height(cam: Camera, kp: np.ndarray, court_xy: np.ndarray, prior: float = 1.85):
    """Stature from the eyes' ray above the foot point (median, clamped)."""
    ok = np.isfinite(kp[:, HEAD, 0]) & np.isfinite(court_xy[:, 0])
    if ok.sum() < 10:
        return prior
    eye = above(cam.centre, cam.rays(kp[ok, HEAD, :2]), court_xy[ok])
    return float(np.clip(np.median(eye[:, 2]) / EYE_FRAC, 1.6, 2.1))


def _look(c: np.ndarray, down0=(0.0, 1.0, 0.0)) -> np.ndarray:
    """(F, 3) camera-frame directions -> (F, 3, 3) rotations whose z axis is that ray
    (rows right, down, forward; down as close to the image's as possible)."""
    fwd = c / np.linalg.norm(c, axis=-1, keepdims=True)
    right = np.cross(down0, fwd)
    right /= np.linalg.norm(right, axis=-1, keepdims=True)
    down = np.cross(fwd, right)
    return np.stack([right, down, fwd], axis=1)


def _smooth_px(x: np.ndarray, n: int = 9) -> np.ndarray:

    return savgol(x, n)


def lift_inputs(cam: Camera, kp: np.ndarray, court_xy: np.ndarray, height: float):
    """Filled H36M keypoints -> MotionBERT input (F, 17, 3) and the per-frame virtual
    camera rotations (F, 3, 3) (world -> virtual camera)."""
    pel = _smooth_px(kp[:, PELVIS, :2])
    r_rel = _look(cam.cam_rays(pel))
    q = np.einsum("fij,fkj->fki", r_rel, cam.cam_rays(kp[..., :2]))
    n = q[..., :2] / q[..., 2:3]
    root = np.column_stack([court_xy, np.full(len(kp), PELVIS_FRAC * height)])
    dist = np.linalg.norm(root - cam.centre, axis=-1)
    x = np.concatenate([n * (dist * UNIT_PER_M)[:, None, None], kp[..., 2:3]], axis=-1)
    return x, r_rel @ cam.r


def _level(o: np.ndarray) -> np.ndarray:
    """Rotate (F, 17, 3) root-relative joints so the median spine is vertical (capped)."""
    s = np.nanmedian(o[:, THORAX] - o[:, PELVIS], axis=0)
    s /= np.linalg.norm(s)
    axis = np.cross(s, EZ)
    sn = np.linalg.norm(axis)
    ang = min(np.arctan2(sn, s @ EZ), np.radians(MAX_TILT_DEG))
    if sn < 1e-9:
        return o
    a = axis / sn
    kx = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    rot = np.eye(3) + np.sin(ang) * kx + (1 - np.cos(ang)) * kx @ kx
    return o @ rot.T


def ankle_floor(cam: Camera, kp: np.ndarray) -> np.ndarray:
    """(F, 2, 2) where the right/left ankle rays meet the flat-foot plane."""
    return floor_hit(cam.centre, cam.rays(kp[:, ANKLES, :2]), ANKLE_H_M)[..., :2]


def place_lifted(
    cam: Camera, kp: np.ndarray, y3d: np.ndarray, r_virt: np.ndarray, court_xy, height: float
) -> np.ndarray:
    """MotionBERT output (F, 17, 3) normalised, virtual-camera axes -> court metres."""
    o = np.einsum("fji,fkj->fki", r_virt, y3d / UNIT_PER_M)  # R_v^T y, per frame
    o = o - o[:, PELVIS : PELVIS + 1]
    o = _level(o)
    o *= height / stature(o)
    return _translate(cam, kp, o, court_xy)


def _translate(cam: Camera, kp: np.ndarray, o: np.ndarray, court_xy: np.ndarray) -> np.ndarray:
    """Root-relative joints -> placed: ankles onto their measured floor points (within
    0.75 m of the tracked foot point), the lower ankle at flat-foot height."""
    feet = ankle_floor(cam, kp)  # (F, 2, 2)
    from_track = court_xy - o[:, ANKLES, :2].mean(axis=1)
    cand = feet - o[:, ANKLES, :2]
    from_feet = _nanmean(cand, axis=1)
    off = from_feet - from_track
    n = np.linalg.norm(off, axis=-1, keepdims=True)
    root = from_track + np.where(
        np.isfinite(n), off * np.minimum(1.0, 0.75 / np.maximum(n, 1e-9)), 0
    )
    out = o.copy()
    out[..., :2] += root[:, None, :]
    return out


def _facing(x: np.ndarray) -> np.ndarray:
    """(F, 3) horizontal facing from the right-minus-left hip+shoulder vector; frames where
    it is too short (side-on) are interpolated from their neighbours."""
    r = (x[:, HIPS[0]] - x[:, HIPS[1]]) + (x[:, SHOULDERS[0]] - x[:, SHOULDERS[1]])
    r[:, 2] = 0
    f = np.cross(EZ, r)
    n = np.linalg.norm(f, axis=-1)
    ok = n > 0.12
    if not ok.any():
        return np.tile([1.0, 0.0, 0.0], (len(x), 1))
    ang = np.unwrap(np.arctan2(f[ok, 1], f[ok, 0]))
    idx = np.arange(len(x))
    a = np.interp(idx, idx[ok], ang)
    return np.column_stack([np.cos(a), np.sin(a), np.zeros(len(x))])


def place_analytic(cam: Camera, kp: np.ndarray, court_xy: np.ndarray, height: float):
    """Rays + fixed bone lengths (no learned model)."""
    lengths = bone_lengths(height)
    c = cam.centre
    d = cam.rays(kp[..., :2])  # (F, 17, 3)
    feet = floor_hit(c, d[:, ANKLES], ANKLE_H_M)
    mid = _nanmean(feet[..., :2], axis=1)
    mid = np.where(np.isfinite(mid), mid, court_xy)
    pel = above(c, d[:, PELVIS], mid)
    pel[:, 2] = np.clip(pel[:, 2], 0.4 * height, 0.62 * height)
    nrm = pel - c  # the body plane: vertical, through the pelvis, facing the camera
    nrm[:, 2] = 0
    nrm /= np.linalg.norm(nrm, axis=-1, keepdims=True)
    s = np.sum((pel - c) * nrm, axis=-1)[:, None] / np.sum(d * nrm[:, None], axis=-1)
    face = _facing(c + s[..., None] * d)  # from the joints' rays cut by that plane
    side = np.cross(face, EZ)  # the player's right
    y = np.full_like(d, np.nan)
    y[:, PELVIS] = pel
    for p, ch in BONES:
        # the child is where its ray meets the sphere of the bone's length around the
        # parent: two roots (near, far); pick by which way the joint should sit
        dc, rel = d[:, ch], y[:, p] - c
        b = np.sum(dc * rel, axis=-1)
        bl = lengths[(p, ch)]
        disc = b * b - (np.sum(rel * rel, axis=-1) - bl * bl)
        root = np.sqrt(np.clip(disc, 0.0, None))
        cand = np.stack([c + (b - root)[:, None] * dc, c + (b + root)[:, None] * dc], axis=1)
        o = cand - y[:, p, None]  # no intersection: the closest point, pulled to length
        o *= (bl / np.maximum(np.linalg.norm(o, axis=-1), 1e-9))[..., None]
        up, fw, rt = PRIOR[ch]  # the bone direction a standing player most likely has
        prior = up * EZ + fw * face + rt * side
        k = _pick(o, prior / np.linalg.norm(prior, axis=-1, keepdims=True), bl)
        y[:, ch] = y[:, p] + o[np.arange(len(o)), k]
    # a foot whose floor point is within the leg's reach stands there (two-bone IK, knee
    # bent toward the facing); out of reach it is in the air and keeps the chain
    for a, kn, hp in zip(ANKLES, KNEES, HIPS, strict=True):
        l1, l2 = lengths[(hp, kn)], lengths[(kn, a)]
        foot = np.column_stack([feet[:, ANKLES.index(a), :2], np.full(len(y), ANKLE_H_M)])
        for f in np.flatnonzero(np.linalg.norm(foot - y[:, hp], axis=-1) < 0.98 * (l1 + l2)):
            y[f, kn], y[f, a] = _ik_knee(y[f, hp], foot[f], y[f, hp] + face[f], l1, l2)
    return y


def _pick(o: np.ndarray, prior: np.ndarray, length: float, smooth: float = 2.0) -> np.ndarray:
    """Which of the two candidate bone vectors (F, 2, 3) per frame: agree with the prior
    direction, and change little between frames (2-state Viterbi; no flip-flopping)."""
    unary = np.nan_to_num(1.0 - np.einsum("fsk,fk->fs", o, prior) / length)
    n = len(o)
    cost = unary[0].copy()
    back = np.zeros((n, 2), int)
    for f in range(1, n):
        pair = np.linalg.norm(o[f][None, :, :] - o[f - 1][:, None, :], axis=-1)  # (prev, cur)
        tot = cost[:, None] + smooth * np.nan_to_num(pair) / length
        back[f] = np.argmin(tot, axis=0)
        cost = tot.min(axis=0) + unary[f]
    k = np.zeros(n, int)
    k[-1] = int(np.argmin(cost))
    for f in range(n - 1, 0, -1):
        k[f - 1] = back[f, k[f]]
    return k
