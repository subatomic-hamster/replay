"""D-89: score exported player tracks against a hand-checked identity GT.

GT: samples/truth/<clip>_identity.json (people's boxes at 10 Hz, source pixels).
Tracks: a processed game's tracks/ dir (replay.tracks.v1 chunks, frame-normalised boxes).

A player id is "on" GT person P at t when its box has IoU >= 0.5 with P's box.
  ids        player ids exported
  purity     per person, share of their matched time on their one best id
  switches   per person, changes of the matched id over time (gaps skipped), summed
  follow_*   N random picks (t0, P, the id on P at t0) followed 30 s at 10 Hz:
             right = the id's box on P, wrong = on someone or nothing else, gone = no box
             (shares of all the followed time); right_of_visible = right over the time P
             is in the GT at all (off screen or hidden, nobody can be right)
  lag_px     matched box centre offset along P's motion (P moving > 100 px/s; negative =
             the box trails the person), off_px the median distance (both 1080p pixels)

Usage: python gt_eval.py <gt.json> <tracks dir>...   (env PICKS, default 1000; round 2
used 200)
"""

# ttsr-ignore: py/no-print — command-line evaluation script, prints are its output
import glob
import json
import os
import sys

import numpy as np


def iou(a, b) -> float:
    iw = max(0.0, min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]))
    ih = max(0.0, min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]))
    i = iw * ih
    return i / (a[2] * a[3] + b[2] * b[3] - i + 1e-9)


def load_tracks(d: str, w: int, h: int) -> dict:
    at = {}
    for f in sorted(glob.glob(f"{d}/*.json")):
        for fr in json.load(open(f))["frames"]:
            at[round(fr["t"], 1)] = {
                p["id"]: [p["bb"][0] * w, p["bb"][1] * h, p["bb"][2] * w, p["bb"][3] * h]
                for p in fr["p"]
            }
    return at


def evaluate(gt_doc: dict, d: str) -> dict:
    w, h = gt_doc["clip"]["size"]
    gt = {round(fr["t"], 1): fr["p"] for fr in gt_doc["frames"]}
    times = sorted(gt)
    at = load_tracks(d, w, h)
    on = {}
    for t in times:
        here = at.get(t, {})
        for q, gb in gt[t].items():
            best = max(here.items(), key=lambda kv: iou(kv[1], gb), default=None)
            if best and iou(best[1], gb) >= 0.5:
                on[(t, q)] = best[0]
    switches = pure = total = 0
    for q in gt_doc["people"]:
        seq = [on[(t, q)] for t in times if (t, q) in on]
        switches += sum(a != b for a, b in zip(seq, seq[1:], strict=False))
        if seq:
            pure += max(seq.count(i) for i in set(seq))
            total += len(seq)
    rng = np.random.default_rng(7)
    keys = sorted(on)
    right = wrong = gone = visible = 0
    for k in rng.choice(len(keys), int(os.environ.get("PICKS", 1000))):
        t0, q = keys[k]
        pid = on[(t0, q)]
        for s in range(301):
            t = round(t0 + s / 10, 1)
            if t not in gt:
                continue
            visible += q in gt[t]
            bb = at.get(t, {}).get(pid)
            if bb is None:
                gone += 1
            elif q in gt[t] and iou(bb, gt[t][q]) >= 0.5:
                right += 1
            else:
                wrong += 1
    n = right + wrong + gone
    along, dist = [], []
    for (t, q), pid in on.items():
        a, b = gt.get(round(t - 0.2, 1), {}).get(q), gt.get(round(t + 0.2, 1), {}).get(q)
        if not (a and b):
            continue
        v = np.array([b[0] + b[2] / 2 - a[0] - a[2] / 2, b[1] + b[3] - a[1] - a[3]]) / 0.4
        g, s = gt[t][q], at[t][pid]
        off = np.array([s[0] + s[2] / 2 - g[0] - g[2] / 2, s[1] + s[3] - g[1] - g[3]])
        dist.append(float(np.linalg.norm(off)))
        if np.linalg.norm(v) > 100:
            along.append(float(off @ v / np.linalg.norm(v)))
    return {
        "tracks": d,
        "ids": len({i for fr in at.values() for i in fr}),
        "purity": round(pure / max(total, 1), 3),
        "switches": switches,
        "follow_right": round(right / n, 3),
        "follow_wrong": round(wrong / n, 3),
        "follow_gone": round(gone / n, 3),
        "right_of_visible": round(right / max(visible, 1), 3),
        "lag_px": round(float(np.mean(along)), 1) if along else None,
        "off_px": round(float(np.median(dist)), 1) if dist else None,
    }


if __name__ == "__main__":
    doc = json.load(open(sys.argv[1]))
    for tracks_dir in sys.argv[2:]:
        print(json.dumps(evaluate(doc, tracks_dir)))
