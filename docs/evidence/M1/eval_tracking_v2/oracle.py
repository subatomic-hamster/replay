"""Ceilings for identity on the current tracklets (synthetic GT only).
usage: oracle.py <clip_dir> <out_dir>
  link  : court tracklets grouped by their majority GT id (perfect merging, no splitting)
  split : tracklets cut where the GT id changes, then grouped (perfect splitting + merging)
"""

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from courtcam.court import read_court_tracks
from courtcam.metrics import _assign, evaluate, gt_frames, iou_matrix

clip, out = Path(sys.argv[1]), Path(sys.argv[2])
truth = json.loads((clip / "ground_truth.json").read_text())
dets = json.loads((out / "_work" / "dets.json").read_text())
sampled = {int(fr["f"]) for fr in dets["frames"]}
g, ig = gt_frames(truth, sampled, oncourt_only=True, min_vis=0.3)
gall = {
    int(fr["f"]): [(d["id"], d["bb"]) for d in fr["d"] if d["oncourt"]] for fr in truth["frames"]
}
ct, _ = read_court_tracks(out / "_work" / "court.json")

rows = defaultdict(list)
for c in ct:
    for f, b in zip(c.tracklet.frames.tolist(), c.tracklet.boxes.tolist(), strict=True):
        rows[f].append((c.track_id, b))
lab = {}
for f, rs in rows.items():
    gg = gall.get(f, [])
    if gg:
        m = iou_matrix(np.array([b for _, b in gg]), np.array([b for _, b in rs]))
        for a, b in _assign(m, 0.5):
            lab[(rs[b][0], f)] = gg[a][0]


def score(pp):
    return {k: evaluate(g, pp, ignore=ig)[k] for k in ("mota", "idf1", "id_switches")}


link, split = defaultdict(list), defaultdict(list)
for c in ct:
    fr = c.tracklet.frames.tolist()
    ids = [lab.get((c.track_id, f), -1) for f in fr]
    known = [x for x in ids if x > 0]
    maj = Counter(known).most_common(1)[0][0] if known else 10_000 + c.track_id
    cur = maj
    for f, b, x in zip(fr, c.tracklet.boxes, ids, strict=True):
        if f not in sampled:
            continue
        link[f].append((maj, np.asarray(b)))
        cur = x if x > 0 else cur
        split[f].append((cur, np.asarray(b)))
print(
    json.dumps({"clip": clip.name, "link": score(dict(link)), "split": score(dict(split))})
)  # ttsr-ignore: py/no-print (CLI output)
