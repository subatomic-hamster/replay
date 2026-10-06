"""Run courtcam.pipeline on one synthetic clip dir. usage: run1.py <clip_dir> <out_dir> [detector] [pose] [asr_model]"""

import json
import sys
import time
from pathlib import Path

from courtcam import pipeline

clip, out = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
# ultralytics resolves "yolo11m.pt" against the cwd: use the shared copies, never download
import os

os.chdir("/workspace/wt/replay-env/models/yolo")
det = sys.argv[3] if len(sys.argv) > 3 else "synthetic"
pose = sys.argv[4] if len(sys.argv) > 4 else "auto"
asr = sys.argv[5] if len(sys.argv) > 5 and sys.argv[5] != "-" else None
meta = json.loads((clip / "plays.json").read_text())
times = {}
last = {"s": None, "t": time.time()}


def prog(stage, frac):
    if stage != last["s"]:
        last.update(s=stage, t=time.time())
    if frac >= 1.0:
        times[stage] = round(time.time() - last["t"], 2)


pipeline.run(
    clip / "clip.mp4",
    out,
    sport=meta["sport"],
    variant=meta["variant"],
    detector=det,
    ground_truth=clip / "ground_truth.json",
    calib=clip / "landmarks.json",
    show_progress=False,
    pose=pose,
    asr_model=asr,
    progress=prog,
)
print(json.dumps(times))  # ttsr-ignore: py/no-print (CLI output)
