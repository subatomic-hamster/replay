"""The H36M-17 skeleton (MotionBERT's joint order), COCO-17 conversion and the
anthropometric bone lengths both placement paths share."""

from __future__ import annotations

import numpy as np

JOINTS = (
    "pelvis", "r_hip", "r_knee", "r_ankle", "l_hip", "l_knee", "l_ankle", "spine", "thorax",
    "nose", "head", "l_shoulder", "l_elbow", "l_wrist", "r_shoulder", "r_elbow", "r_wrist",
)  # fmt: skip
PARENT = (-1, 0, 1, 2, 0, 4, 5, 0, 7, 8, 9, 8, 11, 12, 8, 14, 15)
BONES = tuple((PARENT[j], j) for j in range(1, len(JOINTS)))
PELVIS, SPINE, THORAX, NOSE, HEAD = 0, 7, 8, 9, 10
ANKLES = (3, 6)  # right, left
KNEES = (2, 5)
HIPS = (1, 4)
SHOULDERS = (14, 11)
WRISTS = (16, 13)  # right, left
FLIP = (0, 4, 5, 6, 1, 2, 3, 7, 8, 9, 10, 14, 15, 16, 11, 12, 13)  # left <-> right
LIMBS = (2, 3, 5, 6, 12, 13, 15, 16)  # knees, ankles, elbows, wrists

# Bone length as a fraction of stature (Drillis & Contini segment table, H36M joint
# definitions: head = mid-eyes, hips at the hip joints, thorax = mid-shoulders).
BONE_FRAC = {
    (0, 1): 0.095, (0, 4): 0.095,  # pelvis -> hip
    (1, 2): 0.245, (4, 5): 0.245,  # thigh
    (2, 3): 0.246, (5, 6): 0.246,  # shank
    (0, 7): 0.144, (7, 8): 0.144,  # pelvis -> spine -> thorax (hip 0.53 h -> shoulder 0.818 h)
    (8, 9): 0.100, (9, 10): 0.030,  # thorax -> nose -> mid-eyes
    (8, 11): 0.130, (8, 14): 0.130,  # thorax -> shoulder
    (11, 12): 0.186, (14, 15): 0.186,  # upper arm
    (12, 13): 0.146, (15, 16): 0.146,  # forearm
}  # fmt: skip
# ankle -> knee -> hip -> pelvis-height chain -> eyes, as a fraction of stature
CHAIN = ((2, 3), (1, 2), (0, 7), (7, 8), (8, 9), (9, 10))
CHAIN_FRAC = sum(BONE_FRAC[b] for b in CHAIN)
ANKLE_H_M = 0.08  # ankle joint above the floor when the foot is flat
EYE_FRAC = 0.936  # eye height / stature
PELVIS_FRAC = 0.53


def bone_lengths(height_m: float) -> dict[tuple[int, int], float]:
    return {b: f * height_m for b, f in BONE_FRAC.items()}


def coco_to_h36m(kp: np.ndarray, *, scored: bool = True) -> np.ndarray:
    """(..., 17, C) COCO-17 -> H36M-17 (MotionBERT's mapping). `scored`: the last of
    3 channels is a confidence (a joint made from two keypoints gets the lower one);
    False for (x, y, z) points."""
    kp = np.asarray(kp, dtype=np.float64)
    out = np.empty_like(kp)
    score = scored and kp.shape[-1] == 3

    def mid(a: np.ndarray, b: np.ndarray) -> np.ndarray:
        m = (a + b) / 2
        if score:
            m[..., 2] = np.minimum(a[..., 2], b[..., 2])
        return m

    for h, c in ((1, 12), (2, 14), (3, 16), (4, 11), (5, 13), (6, 15), (9, 0),
                 (11, 5), (12, 7), (13, 9), (14, 6), (15, 8), (16, 10)):  # fmt: skip
        out[..., h, :] = kp[..., c, :]
    out[..., 0, :] = mid(kp[..., 11, :], kp[..., 12, :])
    out[..., 8, :] = mid(kp[..., 5, :], kp[..., 6, :])
    out[..., 10, :] = mid(kp[..., 1, :], kp[..., 2, :])
    out[..., 7, :] = mid(out[..., 0, :], out[..., 8, :])
    return out


def rest_pose(height: float = 1.85, xy=(0.0, 0.0), face: float = 0.0) -> np.ndarray:
    """(17, 3) upright skeleton with anthropometric bones standing at court `xy`,
    facing angle `face` (rad): arms down, forearms forward. For tests and fixtures."""
    L = bone_lengths(height)
    f = np.array([np.cos(face), np.sin(face), 0.0])
    r = np.cross(f, [0.0, 0.0, 1.0])  # the player's right
    z = np.array([0.0, 0.0, 1.0])
    j = np.zeros((17, 3))
    j[0] = [xy[0], xy[1], ANKLE_H_M + L[(2, 3)] + L[(1, 2)]]
    j[1], j[4] = j[0] + r * L[(0, 1)], j[0] - r * L[(0, 4)]
    j[2], j[5] = j[1] - z * L[(1, 2)], j[4] - z * L[(4, 5)]
    j[3], j[6] = j[2] - z * L[(2, 3)], j[5] - z * L[(5, 6)]
    j[7] = j[0] + z * L[(0, 7)]
    j[8] = j[7] + z * L[(7, 8)]
    j[9] = j[8] + (0.8 * z + 0.6 * f) * L[(8, 9)]
    j[10] = j[9] + z * L[(9, 10)]
    j[14], j[11] = j[8] + r * L[(8, 14)], j[8] - r * L[(8, 11)]
    elbow = (-0.9 * z + 0.436 * f) / np.linalg.norm(-0.9 * z + 0.436 * f)
    j[15], j[12] = j[14] + elbow * L[(14, 15)], j[11] + elbow * L[(11, 12)]
    j[16], j[13] = j[15] + f * L[(15, 16)], j[12] + f * L[(12, 13)]
    return j


def h36m_to_coco(j: np.ndarray) -> np.ndarray:
    """(..., 17, 3) H36M points -> COCO-17 points (eyes/ears made up around the head)."""
    out = np.empty(j.shape[:-2] + (17, 3))
    for c, h in ((0, 9), (5, 11), (6, 14), (7, 12), (8, 15), (9, 13), (10, 16), (11, 4),
                 (12, 1), (13, 5), (14, 2), (15, 6), (16, 3)):  # fmt: skip
        out[..., c, :] = j[..., h, :]
    lat = (j[..., 14, :] - j[..., 11, :]) * 0.12  # toward the right shoulder
    for c, k in ((1, -1), (2, 1), (3, -2.5), (4, 2.5)):
        out[..., c, :] = j[..., 10, :] + k * lat
    return out


def stature(joints: np.ndarray) -> float:
    """Stature implied by the median ankle-to-eyes chain of (F, 17, 3) joints."""
    total = 0.0
    for p, c in CHAIN:
        d = np.linalg.norm(joints[:, c] - joints[:, p], axis=-1)
        if c in ANKLES or c in KNEES:  # average both legs
            d = (d + np.linalg.norm(joints[:, FLIP[c]] - joints[:, FLIP[p]], axis=-1)) / 2
        total += float(np.nanmedian(d))
    return total / CHAIN_FRAC
