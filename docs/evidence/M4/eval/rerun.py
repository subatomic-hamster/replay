"""Re-run pose -> events -> triggers -> plays on a finished run with profile overrides.

usage: rerun.py <src_run> <dst_run> <pose: yolo|vit|synthetic|keep> [--model M] [--gt GT] [k.f=v ...]
  keep: dst already has poses/ (only the downstream stages run).
Prints stage timings as JSON. Overrides are dotted profile fields, values JSON or str.
"""

import json
import shutil
import sys
import time
from pathlib import Path

from courtcam.ingest import probe
from courtcam.profiles import load_profile

from courtcam import pipeline as P

args = sys.argv[1:]
src, dst, kind = Path(args[0]), Path(args[1]), args[2]
model = gt = None
sets = []
rest = args[3:]
while rest:
    a = rest.pop(0)
    if a == "--model":
        model = rest.pop(0)
    elif a == "--gt":
        gt = Path(rest.pop(0))
    else:
        sets.append(a)
if kind == "keep" and src.resolve() != dst.resolve():
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
elif kind != "keep":
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(
        src,
        dst,
        ignore=shutil.ignore_patterns(
            "poses", "events.json", "triggers.json", "plays.json", "clips.json", "score.json"
        ),
    )
game = json.loads((dst / "game.json").read_text())
profile = load_profile(game["sport"])


def override(obj, path, value):
    head, *tail = path
    if not tail:
        return obj.model_copy(update={head: value})
    return obj.model_copy(update={head: override(getattr(obj, head), tail, value)})


for s in sets:
    k, v = s.split("=", 1)
    try:
        v = json.loads(v)
    except json.JSONDecodeError:
        pass
    profile = override(profile, k.split("."), v)
info = probe(dst / "media" / "wide.mp4")
calib = P.calib_mod.read_calib(dst / "calib.json")
times = {}
noop = lambda s, f: None
t = time.time()
if kind != "keep":
    P.stage_pose(dst, profile, info, kind=kind, model=model, ground_truth=gt, progress=noop)
    times["pose"] = round(time.time() - t, 2)
t = time.time()
P.stage_events(dst, profile, calib, info, labeler=None, progress=noop)
times["events"] = round(time.time() - t, 2)
t = time.time()
P.stage_triggers(dst, profile, info, progress=noop)
P.stage_plays(dst, profile, info, progress=noop)
times["triggers+plays"] = round(time.time() - t, 2)
print(json.dumps(times))  # ttsr-ignore: py/no-print (CLI)
