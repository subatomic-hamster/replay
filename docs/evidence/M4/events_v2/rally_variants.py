"""Rally P/R (tIoU >= 0.5) of the current detect_rallies with rally.audio_extend_end off / on and
with rally.audio_fusion, re-run over a finished pipeline output.

usage: rally_variants.py real <name> <out_dir>     (hand labels: samples-real/<name>.rallies.json)
       rally_variants.py synth <clip_dir> <out_dir> [<clip_dir> <out_dir> ...]   (synthetic GT)
"""

import json
import sys
from pathlib import Path

from courtcam.events import detect_rallies
from courtcam.identity import read_players
from courtcam.profiles import load_profile

from courtcam import pipeline

VARIANTS = [
    ("motion", {"audio_extend_end": False}),
    ("extend_end", {}),
    ("fusion", {"audio_fusion": True}),
]


def tiou(a, b):
    inter = max(0.0, min(a[1], b[1]) - max(a[0], b[0]))
    return inter / (max(a[1], b[1]) - min(a[0], b[0]))


def score(pred, gt):
    used, tp = set(), 0
    for g in gt:
        c = [(tiou(p, g), k) for k, p in enumerate(pred) if k not in used and tiou(p, g) >= 0.5]
        if c:
            used.add(max(c)[1])
            tp += 1
    return tp, len(pred), len(gt)


def run(out: Path, sport: str, gt, calib):
    info = json.loads((out / "game.json").read_text())
    players, _ = read_players(out / "_work" / "players.json")
    v = info["video"]
    sig = pipeline.signals(out, type("I", (), {"width": v["width"], "height": v["height"]})())
    base = load_profile(sport)
    res = {}
    for label, upd in VARIANTS:
        prof = base.model_copy(update={"rally": base.rally.model_copy(update=upd)})
        ev = detect_rallies(Path("x"), players, prof, calib, signals=sig)
        res[label] = score([(e.t_start, e.t_end) for e in ev if e.type == "rally"], gt)
    return res


mode, args = sys.argv[1], sys.argv[2:]
if mode == "real":
    name, out = args[0], Path(args[1])
    truth = json.loads(
        Path(f"/workspace/wt/replay-env/samples-real/{name}.rallies.json").read_text()
    )
    dur = json.loads((out / "game.json").read_text())["video"]["duration_s"]
    pairs = [(name, run(out, "badminton", [tuple(r) for r in truth["rallies"] if r[0] < dur], {}))]
else:
    pairs = []
    for i in range(0, len(args), 2):
        clip, out = Path(args[i]), Path(args[i + 1])
        g = json.loads((clip / "ground_truth.json").read_text())
        gt = [
            (e["t_start"], e["t_end"])
            for e in json.loads((clip / "events.json").read_text())["events"]
            if e["type"] == "rally"
        ]
        pairs.append((clip.name, run(out, g["sport"], gt, {"variant": g["variant"]})))
tot: dict[str, list[int]] = {}
for name, res in pairs:
    print(name, {k: f"{tp}/{n}/{g}" for k, (tp, n, g) in res.items()})  # ttsr-ignore: py/no-print
    for k, (tp, n, g) in res.items():
        t = tot.setdefault(k, [0, 0, 0])
        t[0] += tp
        t[1] += n
        t[2] += g
for k, (tp, n, g) in tot.items():
    print(
        f"TOTAL {k}: tp {tp} P {tp / max(n, 1):.3f} R {tp / max(g, 1):.3f}"
    )  # ttsr-ignore: py/no-print
