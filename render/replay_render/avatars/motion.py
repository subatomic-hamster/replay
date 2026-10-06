"""Clean-up of per-frame 3D joints (court metres, z up) and the numbers that measure it.

Every function takes (F, 17, 3) joints with NaN rows where the player is absent.

* `savgol` — zero-phase Savitzky-Golay smoothing (no lag, keeps peaks better than a
  moving average), separate windows for the root trajectory and the root-relative pose;
* `fix_bones` — every bone set to its median length (symmetric left/right), walking out
  from the pelvis so directions are kept;
* `contacts` + `pin_feet` — stance detected from ankle speed and height; during a stance
  the ankle is held at one floor point and the knee re-solved by two-bone IK (bone
  lengths kept), blended over a few frames at either end so a step never pops;
* `separate` — overlapping torsos (vertical capsules around pelvis..thorax) pushed
  apart along the floor, the push smoothed in time;
* metrics: `jitter` (acceleration), `foot_slide` (ankle speed in stance), `bone_cv`,
  `penetration`, `mpjpe`.
"""

from __future__ import annotations

import numpy as np

from ..virtual.tierb import _smooth
from .skeleton import ANKLE_H_M, ANKLES, BONES, FLIP, HIPS, KNEES, PELVIS, THORAX

CONTACT_V = 0.4  # m/s: an ankle slower than this ...
CONTACT_H = 0.12  # m: ... and this close to its flat-foot height is planted
MIN_RUN = 3  # frames: shorter stances / gaps are noise
BLEND = 6  # frames to ease in/out of a pinned stance
TORSO_R = 0.25  # m: torso capsule radius for collision avoidance


def _coeffs(window: int, order: int) -> np.ndarray:
    m = window // 2
    a = np.vander(np.arange(-m, m + 1, dtype=np.float64), order + 1, increasing=True)
    return np.linalg.pinv(a)[0]


def _segments(ok: np.ndarray) -> list[tuple[int, int]]:
    """[start, end) runs of True."""
    d = np.diff(np.r_[0, ok.astype(np.int8), 0])
    return list(zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1), strict=True))


def savgol(x: np.ndarray, window: int, order: int = 2) -> np.ndarray:
    """Savitzky-Golay along axis 0 of (F, ...) per run of finite frames; the first and
    last half-windows are evaluated on the polynomial fitted to the end window."""
    x = np.asarray(x, dtype=np.float64)
    out = x.copy()
    flat = x.reshape(len(x), -1)
    ok = np.isfinite(flat).all(axis=1)
    o = out.reshape(len(x), -1)
    for a, b in _segments(ok):
        n = b - a
        w = min(window | 1, n if n % 2 else n - 1)
        if w <= order + 1:
            continue
        m = w // 2
        seg = flat[a:b]
        c = _coeffs(w, order)
        for d in range(flat.shape[1]):
            o[a + m : b - m, d] = np.convolve(seg[:, d], c[::-1], mode="valid")
        v = np.vander(np.arange(w, dtype=np.float64), order + 1, increasing=True)
        fit = np.linalg.pinv(v)
        o[a : a + m] = v[:m] @ (fit @ seg[:w])
        o[b - m : b] = v[w - m :] @ (fit @ seg[n - w :])
    return out


def smooth_joints(j: np.ndarray, fps: float, pose_s: float = 0.27, root_s: float = 0.5):
    """Root trajectory and root-relative pose smoothed with their own windows."""
    root = j[:, PELVIS : PELVIS + 1]
    rel = savgol(j - root, max(5, round(pose_s * fps)))
    return rel + savgol(root, max(5, round(root_s * fps)))


def fix_bones(j: np.ndarray, lengths: dict | None = None) -> np.ndarray:
    """Each bone at its median (or given) length, left/right equal, directions kept."""
    if lengths is None:
        med = {b: float(np.nanmedian(np.linalg.norm(j[:, b[1]] - j[:, b[0]], axis=-1)))
               for b in BONES}  # fmt: skip
        lengths = {b: (med[b] + med[(FLIP[b[0]], FLIP[b[1]])]) / 2 for b in BONES}
    out = j.copy()
    for p, c in BONES:  # parents come first
        d = j[:, c] - j[:, p]
        n = np.linalg.norm(d, axis=-1, keepdims=True)
        out[:, c] = out[:, p] + d / np.maximum(n, 1e-9) * lengths[(p, c)]
    return out


def _clean(mask: np.ndarray, n: int = MIN_RUN) -> np.ndarray:
    m = mask.copy()
    for a, b in _segments(~m):  # fill short gaps between stances
        if 0 < a and b < len(m) and b - a < n:
            m[a:b] = True
    for a, b in _segments(m):  # drop blips
        if b - a < n:
            m[a:b] = False
    return m


def contacts(j: np.ndarray, fps: float) -> np.ndarray:
    """(F, 2) bool: right/left ankle planted (slow and at flat-foot height)."""
    out = np.zeros((len(j), 2), bool)
    for k, a in enumerate(ANKLES):
        p = savgol(j[:, a], max(5, round(0.2 * fps)))
        v = np.gradient(p[:, :2], axis=0) * fps if len(p) > 1 else np.full((len(p), 2), np.inf)
        v = np.linalg.norm(v, axis=-1)
        low = p[:, 2] < ANKLE_H_M + CONTACT_H
        out[:, k] = _clean(np.isfinite(p[:, 0]) & (v < CONTACT_V) & low)
    return out


def ground(j: np.ndarray, fps: float) -> np.ndarray:
    """Shift each frame vertically so the lower ankle sits at flat-foot height; the
    shift itself is smoothed (no bobbing). Jumps are not recovered (README, limits)."""
    dz = ANKLE_H_M - np.min(j[:, ANKLES, 2], axis=1)
    dz = savgol(dz[:, None], max(5, round(0.2 * fps)))[:, 0]
    out = j.copy()
    out[..., 2] += dz[:, None]
    return out


def _ik_knee(hip, ankle, knee0, l1, l2):
    """Knee for a hip..ankle pair with thigh l1, shank l2, bent like `knee0`.
    Returns (knee, ankle) — the ankle pulled in if it is out of reach."""
    v = ankle - hip
    d = float(np.linalg.norm(v))
    reach = (l1 + l2) * 0.999
    if d > reach:
        ankle = hip + v / d * reach
        v, d = ankle - hip, reach
    d = max(d, abs(l1 - l2) + 1e-4)
    axis = v / d
    a = (l1 * l1 - l2 * l2 + d * d) / (2 * d)
    h = np.sqrt(max(l1 * l1 - a * a, 0.0))
    bend = (knee0 - hip) - ((knee0 - hip) @ axis) * axis
    nb = np.linalg.norm(bend)
    bend = bend / nb if nb > 1e-6 else np.array([0.0, 0.0, 1.0])
    return hip + a * axis + h * bend, ankle


def pin_feet(j: np.ndarray, planted: np.ndarray):
    """Hold each planted ankle at one floor point per stance (the stance's median xy)
    with two-bone IK on the leg, easing in and out over `BLEND` frames."""
    out = j.copy()
    F = len(j)
    for k, (a, kn, hp) in enumerate(zip(ANKLES, KNEES, HIPS, strict=True)):
        goal = np.full((F, 3), np.nan)
        w = np.zeros(F)
        for s, e in _segments(planted[:, k]):
            xy = np.nanmedian(j[s:e, a, :2], axis=0)
            lo, hi = max(0, s - BLEND), min(F, e + BLEND)
            for f in range(lo, hi):
                u = 1.0 if s <= f < e else 1.0 - (s - f if f < s else f - e + 1) / (BLEND + 1)
                wf = u * u * u * (u * (u * 6 - 15) + 10)  # smootherstep: no velocity kink
                if wf > w[f]:
                    w[f], goal[f] = wf, (*xy, ANKLE_H_M)
        l1 = float(np.nanmedian(np.linalg.norm(j[:, kn] - j[:, hp], axis=-1)))
        l2 = float(np.nanmedian(np.linalg.norm(j[:, a] - j[:, kn], axis=-1)))
        for f in np.flatnonzero(w > 0):
            if not np.isfinite(j[f, a]).all():
                continue
            ank = j[f, a] + w[f] * (goal[f] - j[f, a])
            out[f, kn], out[f, a] = _ik_knee(j[f, hp], ank, j[f, kn], l1, l2)
    return out


def separate(players: list[np.ndarray], fps: float, radius: float = TORSO_R, iters: int = 6):
    """Push apart overlapping torsos (pelvis..thorax capsules) of all players; returns
    new joint arrays. The per-player push is smoothed, then applied to every joint."""
    if len(players) < 2:
        return [p.copy() for p in players]
    c = np.stack([(p[:, PELVIS, :2] + p[:, THORAX, :2]) / 2 for p in players])  # (P, F, 2)
    pos = c.copy()
    for _ in range(iters):
        for a in range(len(players)):
            for b in range(a + 1, len(players)):
                d = pos[b] - pos[a]
                n = np.linalg.norm(d, axis=-1)
                over = np.isfinite(n) & (n < 2 * radius)
                if not over.any():
                    continue
                u = np.where(n[:, None] > 1e-6, d / np.maximum(n, 1e-6)[:, None], [1.0, 0.0])
                push = np.where(over, (2 * radius - n) / 2, 0.0)[:, None] * u
                pos[a] -= np.nan_to_num(push)
                pos[b] += np.nan_to_num(push)
    out = []
    for p, (src, dst) in enumerate(zip(c, pos, strict=True)):
        # Savitzky-Golay kept the push's step edges and the whole body jerked (32 m/s²
        # peaks). Instead: hold the strongest push within +-r frames (so the overlap
        # keeps nearly all of it), then Gaussian sigma r: eased in and out over ~1 s
        off = np.nan_to_num(dst - src)
        r = max(1, round(0.25 * fps))
        mag = np.linalg.norm(off, axis=1)
        held = [lo + int(np.argmax(mag[lo : f + r + 1])) for f in range(len(off))
                for lo in (max(0, f - r),)]  # fmt: skip
        off = _smooth(off[held], r)
        q = players[p].copy()
        q[..., :2] += off[:, None, :]
        out.append(q)
    return out


# --- metrics ------------------------------------------------------------------------


def jitter(j: np.ndarray, fps: float) -> float:
    """Mean joint acceleration magnitude, m/s² (lower = steadier; real motion adds some)."""
    a = np.linalg.norm(j[2:] - 2 * j[1:-1] + j[:-2], axis=-1) * fps * fps
    return float(np.nanmean(a))


def foot_slide(j: np.ndarray, planted: np.ndarray, fps: float) -> float:
    """Mean horizontal ankle speed while planted, cm/s (0 = no skating)."""
    v = []
    for k, a in enumerate(ANKLES):
        s = np.linalg.norm(np.diff(j[:, a, :2], axis=0), axis=-1) * fps
        m = planted[1:, k] & planted[:-1, k]
        v.append(s[m & np.isfinite(s)])
    v = np.concatenate(v)
    return float(100 * v.mean()) if len(v) else float("nan")


def bone_cv(j: np.ndarray) -> float:
    """Mean coefficient of variation of bone length over time (0 = rigid bones)."""
    cv = []
    for p, c in BONES:
        d = np.linalg.norm(j[:, c] - j[:, p], axis=-1)
        d = d[np.isfinite(d)]
        if len(d) > 1 and d.mean() > 0:
            cv.append(d.std() / d.mean())
    return float(np.mean(cv)) if cv else float("nan")


def penetration(players: list[np.ndarray], radius: float = TORSO_R) -> float:
    """Fraction of player-pair frames whose torso capsules overlap by > 2 cm."""
    c = [(p[:, PELVIS, :2] + p[:, THORAX, :2]) / 2 for p in players]
    hit = tot = 0
    for a in range(len(c)):
        for b in range(a + 1, len(c)):
            n = np.linalg.norm(c[b] - c[a], axis=-1)
            ok = np.isfinite(n)
            tot += int(ok.sum())
            hit += int((n[ok] < 2 * radius - 0.02).sum())
    return hit / tot if tot else 0.0


def mpjpe(pred: np.ndarray, gt: np.ndarray, joints=None, root_relative: bool = False) -> float:
    """Mean per-joint position error in mm over frames where both are finite."""
    p, g = pred, gt
    if joints is not None:
        p, g = p[:, joints], g[:, joints]
    if root_relative:
        p = p - pred[:, PELVIS : PELVIS + 1]
        g = g - gt[:, PELVIS : PELVIS + 1]
    e = np.linalg.norm(p - g, axis=-1)
    return float(1000 * np.nanmean(e))
