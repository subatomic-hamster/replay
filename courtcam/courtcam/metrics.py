"""Multi-object tracking metrics against synthetic ground truth.

CLEAR-MOT (MOTA, ID switches, detection recall/precision) and IDF1, written out here
rather than taken from `motmetrics`: that package pulls in pandas + scipy for ~100 lines
of arithmetic and has had no release since 2022. Assignment uses `lap`, which is
already a courtcam dependency.

Ground-truth boxes whose visible fraction is below `min_vis` (a player hidden behind
another) are *don't care*: a detection on one is neither a hit nor a false positive, and
missing one is not a miss — the MOT17 convention.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import lap
import numpy as np

Frames = dict[int, list[tuple[int, np.ndarray]]]  # frame -> [(id, box xywh)]


def iou_matrix(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """(len(a), len(b)) IoU of xywh boxes."""
    a, b = np.asarray(a, float).reshape(-1, 4), np.asarray(b, float).reshape(-1, 4)
    ax1, ay1, bx1, by1 = a[:, 0] + a[:, 2], a[:, 1] + a[:, 3], b[:, 0] + b[:, 2], b[:, 1] + b[:, 3]
    iw = np.clip(
        np.minimum(ax1[:, None], bx1[None]) - np.maximum(a[:, None, 0], b[None, :, 0]), 0, None
    )
    ih = np.clip(
        np.minimum(ay1[:, None], by1[None]) - np.maximum(a[:, None, 1], b[None, :, 1]), 0, None
    )
    inter = iw * ih
    union = (a[:, 2] * a[:, 3])[:, None] + (b[:, 2] * b[:, 3])[None] - inter
    return np.where(union > 0, inter / np.maximum(union, 1e-9), 0.0)


def _assign(iou: np.ndarray, thr: float) -> list[tuple[int, int]]:
    if iou.size == 0:
        return []
    _, x, _ = lap.lapjv(1.0 - iou, extend_cost=True, cost_limit=1.0 - thr + 1e-9)
    return [(i, int(j)) for i, j in enumerate(x) if j >= 0 and iou[i, j] >= thr]


def evaluate(
    gt: Frames, pred: Frames, *, iou: float = 0.5, ignore: Frames | None = None
) -> dict[str, Any]:
    """CLEAR-MOT + IDF1 over the frames in `gt` (frames missing from `pred` = no boxes)."""
    ignore = ignore or {}
    n_gt = n_pred = tp = fp = idsw = 0
    last: dict[int, int] = {}  # gt id -> pred id it was last matched to
    pair = defaultdict(int)  # (gt id, pred id) -> frames with IoU >= thr
    gt_count, pred_count = defaultdict(int), defaultdict(int)
    for f in sorted(gt):
        g_ids = [i for i, _ in gt[f]]
        g_box = np.array([b for _, b in gt[f]]).reshape(-1, 4)
        rows = pred.get(f, [])
        p_ids = [i for i, _ in rows]
        p_box = np.array([b for _, b in rows]).reshape(-1, 4)
        m = iou_matrix(g_box, p_box)
        # CLEAR-MOT: keep last frame's correspondences that still overlap, then Hungarian
        matched: dict[int, int] = {}
        for gi, g in enumerate(g_ids):
            if g in last and last[g] in p_ids:
                pj = p_ids.index(last[g])
                if m[gi, pj] >= iou and pj not in matched.values():
                    matched[gi] = pj
        free_g = [gi for gi in range(len(g_ids)) if gi not in matched]
        free_p = [pj for pj in range(len(p_ids)) if pj not in matched.values()]
        for a, b in _assign(m[np.ix_(free_g, free_p)], iou):
            matched[free_g[a]] = free_p[b]
        # unmatched predictions sitting on a don't-care box are dropped, not false positives
        drop: set[int] = set()
        ig = np.array([b for _, b in ignore.get(f, [])]).reshape(-1, 4)
        if len(ig):
            mi = iou_matrix(p_box, ig)
            drop = {
                pj for pj in range(len(p_ids)) if pj not in matched.values() and mi[pj].max() >= iou
            }
        kept = [pj for pj in range(len(p_ids)) if pj not in drop]
        n_gt += len(g_ids)
        n_pred += len(kept)
        tp += len(matched)
        fp += len(kept) - len(matched)
        for gi, pj in matched.items():
            g, p = g_ids[gi], p_ids[pj]
            if g in last and last[g] != p:
                idsw += 1
            last[g] = p
        for gi, g in enumerate(g_ids):
            gt_count[g] += 1
            for pj in kept:
                if m[gi, pj] >= iou:
                    pair[(g, p_ids[pj])] += 1
        for pj in kept:
            pred_count[p_ids[pj]] += 1
    fn = n_gt - tp
    # IDF1: one-to-one gt<->pred identity assignment maximising co-detected frames
    g_list, p_list = sorted(gt_count), sorted(pred_count)
    idtp = 0
    if g_list and p_list:
        w = np.zeros((len(g_list), len(p_list)))
        for (g, p), c in pair.items():
            w[g_list.index(g), p_list.index(p)] = c
        _, x, _ = lap.lapjv(w.max() - w, extend_cost=True)
        idtp = int(sum(w[i, j] for i, j in enumerate(x) if j >= 0))
    return {
        "frames": len(gt),
        "gt": n_gt,
        "pred": n_pred,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "id_switches": idsw,
        "recall": round(tp / n_gt, 4) if n_gt else None,
        "precision": round(tp / n_pred, 4) if n_pred else None,
        "mota": round(1.0 - (fn + fp + idsw) / n_gt, 4) if n_gt else None,
        "idf1": round(2 * idtp / (n_gt + n_pred), 4) if n_gt + n_pred else None,
        "gt_ids": len(g_list),
        "pred_ids": len(p_list),
    }


def gt_frames(
    truth: dict, frames: set[int] | None, *, oncourt_only: bool, min_vis: float
) -> tuple[Frames, Frames]:
    """(boxes to score, don't-care boxes) per frame from a synthetic ground_truth.json."""
    keep: Frames = {}
    ignore: Frames = {}
    for fr in truth["frames"]:
        f = int(fr["f"])
        if frames is not None and f not in frames:
            continue
        keep[f], ignore[f] = [], []
        for d in fr["d"]:
            if oncourt_only and not d["oncourt"]:
                continue
            row = (int(d["id"]), np.asarray(d["bb"], float))
            (keep if d.get("vis", 1.0) >= min_vis else ignore)[f].append(row)
    return keep, ignore


def evaluate_run(
    truth_path: Path, out: Path, *, iou: float = 0.5, min_vis: float = 0.3
) -> dict[str, Any]:
    """Score a `courtcam run` output directory against its synthetic ground truth.

    * `detections`: every box the detector+tracker emitted (`_work/dets.json`, tracker
      ids), against every person in frame — players and spectators alike.
    * `players`: the identity stage's players (`_work/players.json`) against the on-court
      players only, plus the court-position error of matched boxes.
    """
    from .identity import read_players

    truth = json.loads(Path(truth_path).read_text(encoding="utf-8"))
    work = Path(out) / "_work"
    dets = json.loads((work / "dets.json").read_text(encoding="utf-8"))
    sampled = {int(fr["f"]) for fr in dets["frames"]}
    report: dict[str, Any] = {"synthetic": True, "iou": iou, "min_vis": min_vis}

    pred: Frames = {
        int(fr["f"]): [(int(r[0]), np.asarray(r[1:5], float)) for r in fr["d"]]
        for fr in dets["frames"]
    }
    g, ig = gt_frames(truth, sampled, oncourt_only=False, min_vis=min_vis)
    report["detections"] = evaluate(g, pred, iou=iou, ignore=ig)

    if (work / "players.json").exists():
        players, _ = read_players(work / "players.json")
        pp: Frames = defaultdict(list)
        court: dict[tuple[int, int], np.ndarray] = {}
        for k, p in enumerate(players):
            tl = p.track.tracklet
            for f, box, ct in zip(tl.frames.tolist(), tl.boxes, p.track.court_m, strict=True):
                if f in sampled:
                    pp[int(f)].append((k, np.asarray(box, float)))
                    court[(int(f), k)] = ct
        g, ig = gt_frames(truth, sampled, oncourt_only=True, min_vis=min_vis)
        report["players"] = evaluate(g, dict(pp), iou=iou, ignore=ig)
        report["players"]["court_err_m"] = _court_error(truth, g, dict(pp), court, iou)
    return report


def _court_error(
    truth: dict, g: Frames, pred: Frames, court, thr: float
) -> dict[str, float] | None:
    ct = {(int(fr["f"]), int(d["id"])): d["ct"] for fr in truth["frames"] for d in fr["d"]}
    errs = []
    for f, rows in g.items():
        pr = pred.get(f, [])
        if not rows or not pr:
            continue
        m = iou_matrix(np.array([b for _, b in rows]), np.array([b for _, b in pr]))
        for a, b in _assign(m, thr):
            errs.append(
                float(np.linalg.norm(np.asarray(ct[(f, rows[a][0])]) - court[(f, pr[b][0])]))
            )
    if not errs:
        return None
    e = np.asarray(errs)
    return {"median": round(float(np.median(e)), 3), "p90": round(float(np.percentile(e, 90)), 3)}
