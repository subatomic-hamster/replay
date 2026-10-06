"""Re-run triggers + plays on a finished synthetic run with ASR and a simulated roster.

The roster simulates the user tagging players in the TV app: each pipeline player gets
the name of the ground-truth person its boxes overlap most (synthetic only).
usage: run_trig.py <clip_dir> <out_dir> <asr_model|->
"""

import json
import sys
import time
from collections import Counter
from pathlib import Path

from courtcam.ingest import probe
from courtcam.pose import iou
from courtcam.profiles import load_profile

from courtcam import pipeline

clip, out, asr = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
gt = json.loads((clip / "ground_truth.json").read_text())
W, H, FPS = gt["width"], gt["height"], gt["fps"]
frames = {int(f["f"]): f["d"] for f in gt["frames"]}
votes: dict[str, Counter] = {}
for chunk in sorted((out / "tracks").glob("*.json")):
    for fr in json.loads(chunk.read_text())["frames"]:
        rows = frames.get(int(round(fr["t"] * FPS)), [])
        for p in fr["p"]:
            b = (p["bb"][0] * W, p["bb"][1] * H, p["bb"][2] * W, p["bb"][3] * H)
            best = max(rows, key=lambda r: iou(b, tuple(r["bb"])), default=None)
            if best is not None and iou(b, tuple(best["bb"])) > 0.5:
                votes.setdefault(p["id"], Counter())[best["id"]] += 1
names = {p["id"]: p["name"] for p in gt["players"]}
roster = {}
for pid, v in votes.items():
    name = names.get(v.most_common(1)[0][0])
    if name and name not in roster:
        roster[name] = pid
profile = load_profile(gt["sport"])
info = probe(out / "media" / "wide.mp4")
t0 = time.time()
pipeline.stage_triggers(
    out,
    profile,
    info,
    asr_model=None if asr == "-" else asr,
    roster=roster,
    progress=lambda s, f: None,
)
t1 = time.time()
pipeline.stage_plays(out, profile, info, progress=lambda s, f: None)
print(
    json.dumps({"roster": roster, "triggers_s": round(t1 - t0, 2)})
)  # ttsr-ignore: py/no-print (CLI output)
