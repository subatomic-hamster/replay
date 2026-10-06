"""Tier C accuracy and quality on a synthetic clip, against the rig's true 3D joints.

The synthetic generator exports each person's COCO-17 keypoints in court metres
(`ground_truth.json` rows, `kp3`). Each scene player is matched per frame to the
ground-truth person nearest its pelvis. Reported per method (MotionBERT, analytic):

* MPJPE (mm), absolute in court metres and pelvis-aligned, over the 12 joints both
  skeletons define the same way (shoulders, elbows, wrists, hips, knees, ankles) — the
  rig's head/neck/pelvis are defined differently from H36M's;
* jitter (mean joint acceleration, m/s²), foot sliding (ankle speed while planted,
  cm/s), bone-length CV and torso overlap, before and after the clean-up — and the same
  numbers for the ground truth itself, as the floor real motion sets.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from . import motion, scene
from .skeleton import coco_to_h36m, stature

BODY12 = [1, 2, 3, 4, 5, 6, 11, 12, 13, 14, 15, 16]


def ground_truth_joints(gt_path: Path, doc_like: dict, final: dict) -> dict[str, np.ndarray]:
    """(F, 17, 3) true H36M-style joints per scene player (NaN where unmatched)."""
    gt = json.loads(Path(gt_path).read_text(encoding="utf-8"))
    fps, n = doc_like["fps"], doc_like["frames"]
    start = round(doc_like["t_start"] * fps)
    rows = {int(fr["f"]): fr["d"] for fr in gt["frames"]}
    out = {}
    for pid, j in final.items():
        g = np.full((n, 17, 3), np.nan)
        for f in range(n):
            here = [r for r in rows.get(start + f, []) if r.get("kp3")]
            if not here or not np.isfinite(j[f, 0]).all():
                continue
            ct = np.array([r["ct"] for r in here])
            k = int(np.argmin(np.linalg.norm(ct - j[f, 0, :2], axis=1)))
            if np.linalg.norm(ct[k] - j[f, 0, :2]) < 1.0:
                g[f] = coco_to_h36m(np.asarray(here[k]["kp3"]), scored=False)
        out[pid] = g
    return out


def _stack(d: dict) -> np.ndarray:
    return np.concatenate(list(d.values()), axis=0)


def run(game_dir: Path, play_id: str, video: Path, gt_path: Path, out_dir: Path, methods):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    res: dict = {"play_id": play_id}
    keep = {}
    for method in methods:
        doc = scene.build(game_dir, play_id, video, method=method, kp_source="gt",
                          ground_truth=gt_path, keep_raw=True)  # fmt: skip
        raw, final = doc["_raw"], doc["_final"]
        gt = ground_truth_joints(gt_path, doc, final)
        fps = doc["fps"]
        planted = {p["id"]: np.asarray(p["planted"], bool) for p in doc["players"]}
        gt_planted = {pid: motion.contacts(g, fps) for pid, g in gt.items()}
        # body-to-court scale: height from the calibration vs the true skeleton's
        h_err = [abs(p["height_m"] - stature(gt[p["id"]])) * 100 for p in doc["players"]
                 if np.isfinite(gt[p["id"]]).any()]  # fmt: skip
        gt_slide = [motion.foot_slide(g, gt_planted[p], fps) for p, g in gt.items()]
        r = {
            "players": len(final),
            "frames": doc["frames"],
            "mpjpe_mm": {
                k: round(motion.mpjpe(_stack(arr), _stack(gt), BODY12), 1)
                for k, arr in (("before", raw), ("after", final))
            },
            "mpjpe_pelvis_aligned_mm": {
                k: round(motion.mpjpe(_stack(arr), _stack(gt), BODY12, root_relative=True), 1)
                for k, arr in (("before", raw), ("after", final))
            },
            "height_err_cm": round(float(np.nanmean(h_err)), 1),
            "quality": doc["quality"],
            "ground_truth": {
                "jitter_ms2": round(
                    float(np.nanmean([motion.jitter(g, fps) for g in gt.values()])), 3
                ),
                "foot_slide_cms": round(float(np.nanmean(gt_slide)), 2),
                "bone_cv": round(float(np.nanmean([motion.bone_cv(g) for g in gt.values()])), 4),
            },
        }
        res[method] = r
        keep[method] = (raw, final, gt, planted, fps)
        scene.write(out_dir, f"{play_id}_{method}", doc)  # a copy of each method's scene
    (out_dir / f"metrics_{play_id}.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    _plots(keep, out_dir, play_id)
    return res


def _plots(keep: dict, out_dir: Path, play_id: str) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    method = "motionbert" if "motionbert" in keep else next(iter(keep))
    raw, final, gt, planted, fps = keep[method]
    pid = max(final, key=lambda p: np.isfinite(final[p][:, 0, 0]).sum())
    t = np.arange(len(final[pid])) / fps
    fig, ax = plt.subplots(3, 1, figsize=(9, 8), sharex=True)
    for k, (a, name) in enumerate(((3, "right ankle"), (6, "left ankle"))):
        for arr, lab, st in ((raw, "before", "-"), (final, "after", "-"), (gt, "truth", ":")):
            v = np.linalg.norm(np.diff(arr[pid][:, a, :2], axis=0), axis=-1) * fps
            ax[k].plot(t[1:], v, st, label=lab, lw=1.2)
        m = planted[pid][:, k]
        ax[k].fill_between(t, 0, m * 3.0, color="0.85", step="mid", label="planted (detected)")
        ax[k].set_ylabel(f"{name} speed, m/s")
        ax[k].set_ylim(0, 3.0)
        ax[k].legend(loc="upper right", fontsize=8)
    for arr, lab in ((raw, "before"), (final, "after"), (gt, "truth")):
        acc = np.linalg.norm(np.diff(arr[pid], n=2, axis=0), axis=-1).mean(axis=1) * fps * fps
        ax[2].plot(t[2:], acc, label=lab, lw=1.0)
    ax[2].set_ylabel("mean joint accel, m/s²")
    ax[2].set_xlabel("s")
    ax[2].legend(loc="upper right", fontsize=8)
    fig.suptitle(f"Tier C {method}: player {pid}, play {play_id} (synthetic)")
    fig.tight_layout()
    fig.savefig(out_dir / f"quality_{play_id}.png", dpi=80)
    plt.close(fig)
