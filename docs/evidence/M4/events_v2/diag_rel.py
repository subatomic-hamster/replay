"""Per GT shot: the shooter's arms-up runs (start, length) around the release under each
`release_up_min` ("none" = wrists above the nose), from the synthetic GT keypoints, and whether
the run in <out_dir> found the shot. Shows why release_max_s 0.9 dropped shots.

usage: diag_rel.py <clip_dir> <out_dir> [up_min ...]   e.g. ... none -0.2
"""

import json
import sys
from pathlib import Path

import numpy as np
from courtcam.events import _runs, arms_up, x_pose

clip, out = Path(sys.argv[1]), Path(sys.argv[2])
ups = [None if a == "none" else float(a) for a in sys.argv[3:]] or [None, -0.2]
gt = json.loads((clip / "ground_truth.json").read_text())
FPS = gt["fps"]
shots = [e for e in json.loads((clip / "events.json").read_text())["events"] if e["type"] == "shot"]
pred = [e for e in json.loads((out / "events.json").read_text())["events"] if e["type"] == "shot"]
kp_of: dict[str, list] = {}
for f in gt["frames"]:
    for d in f["d"]:
        if d.get("kp"):
            kp_of.setdefault(f"p{d['id']}", []).append((f["f"] / FPS, d["kp"]))
for g in shots:
    rows = [(t, k) for t, k in kp_of.get(g["player_id"], [])
            if g["t_start"] - 2.5 <= t <= g["t_end"] + 0.5]  # fmt: skip
    hit = any(abs(p["t_key"] - g["t_end"]) <= 1.5 for p in pred)
    line = (
        f"GT shot {g['t_start']:.2f}-{g['t_end']:.2f} {g['player_id']} {'HIT ' if hit else 'MISS'}"
    )
    if rows:
        ts = np.array([r[0] for r in rows])
        kp = np.array([r[1] for r in rows], dtype=float).reshape(len(rows), 17, 3)
        # visibility -> score as pose.synthetic_poser does
        kp[:, :, 2] = np.select([kp[:, :, 2] == 2, kp[:, :, 2] == 1], [0.9, 0.4], 0.0)
        for u in ups:
            up = arms_up(kp, up_min=u) & ~x_pose(kp)
            line += (
                f" | up_min={u}: {[(round(a, 2), round(b - a, 2)) for a, b in _runs(ts, up, 0.15)]}"
            )
    print(line)  # ttsr-ignore: py/no-print (diagnostic CLI)
