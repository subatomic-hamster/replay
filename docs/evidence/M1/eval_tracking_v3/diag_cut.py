"""Where does the jersey cut (D-70 `split_switches`) fire, and on what samples? (synthetic only)
usage: diag_cut.py <clip_dir> <out_dir>

Re-runs identity's first steps on <out_dir>/_work/court.json exactly as `identify` does
(sample_appearance -> split_teams -> per-sample torso labels every 2nd sample) and, for
every jersey sample, records: the nearer-centroid label, the distance margin between the
two team centroids, how much of the torso box another tracklet's box covers in that frame
(and whether that box is in front: lower foot point), and the GT id under the sample.
Prints one JSON line per tracklet the cut would split, then a summary line.
"""

import json
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
from courtcam.court import read_court_tracks
from courtcam.metrics import _assign, iou_matrix

from courtcam import identity as I

clip, out = Path(sys.argv[1]), Path(sys.argv[2])
truth = json.loads((clip / "ground_truth.json").read_text())
team_of = {p["id"]: p["team"] for p in truth["players"]}
gt = {int(fr["f"]): [(d["id"], d["bb"]) for d in fr["d"]] for fr in truth["frames"]}
tracks, _ = read_court_tracks(out / "_work" / "court.json")
video = str(out / "media" / "wide.mp4")
hists, _, _ = I.sample_appearance(video, tracks)
teams = I.split_teams(hists)
cents = np.stack([hists[teams == k].mean(axis=0) for k in (0, 1)])

by_frame: dict[int, list[tuple[int, np.ndarray]]] = {}
for i, tr in enumerate(tracks):
    for f, b in zip(tr.tracklet.frames.tolist(), tr.tracklet.boxes, strict=True):
        by_frame.setdefault(int(f), []).append((i, b))


def cover(i: int, f: int, box: np.ndarray) -> tuple[float, bool]:
    """Largest share of i's torso rect covered by another box, and whether it is in front."""
    x, y, w, h = I.torso_rect(box)
    best, front = 0.0, False
    for k, b in by_frame.get(f, []):
        if k == i:
            continue
        iw = min(x + w, b[0] + b[2]) - max(x, b[0])
        ih = min(y + h, b[1] + b[3]) - max(y, b[1])
        c = max(iw, 0) * max(ih, 0) / (w * h)
        if c > best:
            best, front = c, b[1] + b[3] > box[1] + box[3]
    return best, front


def gt_id(f: int, box: np.ndarray) -> int:
    g = gt.get(f, [])
    if not g:
        return -1
    m = iou_matrix(np.array([b for _, b in g]), np.asarray(box)[None])
    a = _assign(m, 0.5)
    return g[a[0][0]][0] if a else -1


wanted: dict[int, list[tuple[int, int]]] = {}
for i, tr in enumerate(tracks):
    for j in range(0, len(tr.tracklet.frames), 2):
        wanted.setdefault(int(tr.tracklet.frames[j]), []).append((i, j))
rows: list[dict[int, dict]] = [{} for _ in tracks]
cap = cv2.VideoCapture(video)
fh, fw = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)), int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
for f, frame in I._grab_frames(cap, sorted(wanted)):
    for i, j in wanted[f]:
        box = tracks[i].tracklet.boxes[j]
        x, y, w, h = I.torso_rect(box)
        crop = frame[max(0, y) : min(fh, y + h), max(0, x) : min(fw, x + w)]
        if not crop.size:
            continue
        d = np.linalg.norm(cents - I._hist(crop)[None], axis=1)
        c, front = cover(i, f, box)
        rows[i][j] = {
            "lab": int(np.argmin(d)),
            "margin": float(abs(d[0] - d[1]) / max(d.max(), 1e-9)),
            "cover": c,
            "front": front,
            "gt": gt_id(f, box),
        }
cap.release()

lab = [{j: r["lab"] for j, r in rw.items()} for rw in rows]
agree = np.mean([v == teams[i] for i, d in enumerate(lab) for v in d.values()])
all_s = [r for rw in rows for r in rw.values()]
wrong_s, cut_s = [], []
for i, tr in enumerate(tracks):
    idx = sorted(lab[i])
    if len(idx) < 2:
        continue
    step = max(float(np.median(np.diff(tr.tracklet.times[idx]))), 1e-3)
    runs = I._runs(np.asarray([lab[i][j] for j in idx]), max(1, round(1.0 / step)))
    wrong_s += [rows[i][j] for j in idx if lab[i][j] != teams[i]]
    if len(runs) < 2:
        continue
    desc = []
    for a, b, team in runs:
        rs = [rows[i][idx[k]] for k in range(a, b)]
        if team != teams[i]:
            cut_s += rs
        ids = Counter(r["gt"] for r in rs).most_common(2)
        desc.append(
            {
                "t": [
                    round(float(tr.tracklet.times[idx[a]]), 2),
                    round(float(tr.tracklet.times[idx[b - 1]]), 2),
                ],
                "label": int(team),
                "samples": b - a,
                "clear_samples": int(sum(r["cover"] <= I.JERSEY_MAX_COVER for r in rs)),
                "min_run": max(1, round(1.0 / step)),
                "own_label_share": round(np.mean([r["lab"] == team for r in rs]), 2),
                "cover_mean": round(np.mean([r["cover"] for r in rs]), 2),
                "cover_gt_0.3": round(np.mean([r["cover"] > 0.3 for r in rs]), 2),
                "front_share": round(np.mean([r["front"] for r in rs]), 2),
                "margin_mean": round(np.mean([r["margin"] for r in rs]), 3),
                "gt_ids": [(int(k), team_of.get(k, -1), n) for k, n in ids],
            }
        )
    print(
        json.dumps({"track": tr.track_id, "team": int(teams[i]), "runs": desc})
    )  # ttsr-ignore: py/no-print (CLI output)


def stats(rs):
    if not rs:
        return {"n": 0}
    return {
        "n": len(rs),
        "cover_mean": round(np.mean([r["cover"] for r in rs]), 3),
        "cover_gt_0.3": round(np.mean([r["cover"] > 0.3 for r in rs]), 3),
        "front_share": round(np.mean([r["front"] for r in rs]), 3),
        "margin_mean": round(np.mean([r["margin"] for r in rs]), 3),
    }


print(  # ttsr-ignore: py/no-print (CLI output)
    json.dumps(
        {
            "clip": clip.name,
            "agree": round(float(agree), 3),
            "all_samples": stats(all_s),
            "off_team_samples": stats(wrong_s),
            "samples_in_cut_runs": stats(cut_s),
        }
    )
)
