"""Variant of docs/evidence/M4/eval/run1.py: run courtcam.pipeline on one synthetic clip
dir only up to the identity stage (all that `courtcam eval` reads).
usage: run_trk.py <clip_dir> <out_dir> <detector> [stages...]   (default stages: ingest..identity)
env (experiments only): TRACKER=<botsort yaml>, STRIDE=<n>
"""

import json
import os
import sys
import time
from pathlib import Path

from courtcam import pipeline

clip, out = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
os.chdir("/workspace/wt/replay-env/models/yolo")
det = sys.argv[3]
stages = sys.argv[4:] or ["ingest", "calibrate", "detect", "track", "court", "identity"]
if os.environ.get("TRACKER"):  # experiment: another tracker yaml
    from courtcam import detect

    d = detect.YoloDetector.__init__.__defaults__
    detect.YoloDetector.__init__.__defaults__ = tuple(
        os.environ["TRACKER"] if v == detect.TRACKER else v for v in d
    )
meta = json.loads((clip / "plays.json").read_text())
t = time.time()
pipeline.run(
    clip / "clip.mp4",
    out,
    sport=meta["sport"],
    variant=meta["variant"],
    detector=det,
    ground_truth=clip / "ground_truth.json",
    calib=clip / "landmarks.json",
    show_progress=False,
    stages=stages,
    stride=int(os.environ.get("STRIDE", 0)) or None,
)
print(
    json.dumps({"stages": stages, "s": round(time.time() - t, 1)})
)  # ttsr-ignore: py/no-print (CLI output)
