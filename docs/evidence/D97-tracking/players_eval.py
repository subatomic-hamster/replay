"""Score a processed game's exported tracks against the hand-labelled player GT
(samples/truth/nottingham_q1_players.json) plus whole-game proxies (no labels).

GT: per instant, boxes classed red / dark (players), referee, ignore, other.
  player_recall  share of red+dark GT boxes with an exported box at IoU >= 0.5 (one-to-one)
  ref_recall     the same for referees
  on_other       exported boxes on a GT "other" box (bench, table, crowd), per instant
  ghost          exported boxes on no GT box at all (IoU < 0.3 with every box), per instant
  off_px         median distance from a matched player's GT box centre to the exported one
  team_acc       matched player boxes whose id's team agrees with the kit, under the best
                 team->kit mapping (0.5 = no better than chance)
Proxies over the whole game (tracks/ at 10 Hz):
  ids, ids_seen5 (seen_s >= 5), people_per_frame, mean_id_life_s, life_in_long_ids (share of
  box time on ids living >= 30 s), gaps (box-time-weighted mean count of disappearances
  > 1 s per id-minute), teams (ids per team)

Usage: python players_eval.py <gt.json> <game dir>...
"""

# ttsr-ignore: py/no-print — command-line evaluation script, prints are its output
import glob
import json
import sys
from pathlib import Path

import numpy as np


def read(path):
    return json.loads(Path(path).read_text())


def iou(a, b) -> float:
    iw = max(0.0, min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]))
    ih = max(0.0, min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]))
    i = iw * ih
    return i / (a[2] * a[3] + b[2] * b[3] - i + 1e-9)


def load(d, w, h):
    at = {}
    for f in sorted(glob.glob(f"{d}/tracks/*.json")):
        for fr in read(f)["frames"]:
            at[round(fr["t"], 1)] = {
                p["id"]: [p["bb"][0] * w, p["bb"][1] * h, p["bb"][2] * w, p["bb"][3] * h]
                for p in fr["p"]
            }
    return at


def evaluate(gt, d):
    w, h = gt["clip"]["size"]
    at = load(d, w, h)
    game = read(f"{d}/game.json")
    team = {p["id"]: p["team"] for p in game["players"]}
    hit = {"red": 0, "dark": 0, "referee": 0}
    n = {"red": 0, "dark": 0, "referee": 0}
    other = ghost = 0
    off, kit_team = [], []
    for fr in gt["frames"]:
        here = dict(at.get(round(fr["t"], 1), {}))
        boxes = [{"bb": b[:4], "class": b[4]} if isinstance(b, list) else b for b in fr["boxes"]]
        pairs = sorted(
            ((iou(eb, g["bb"]), pid, k) for pid, eb in here.items() for k, g in enumerate(boxes)),
            reverse=True,
        )
        used_p, used_g = set(), set()
        for v, pid, k in pairs:
            if v < 0.5 or pid in used_p or k in used_g:
                continue
            used_p.add(pid)
            used_g.add(k)
            c = boxes[k]["class"]
            if c in hit:
                hit[c] += 1
            if c in ("red", "dark"):
                g, e = boxes[k]["bb"], here[pid]
                off.append(
                    np.hypot(g[0] + g[2] / 2 - e[0] - e[2] / 2, g[1] + g[3] / 2 - e[1] - e[3] / 2)
                )
                kit_team.append((c == "red", team.get(pid)))
            elif c == "other":
                other += 1
        for g in boxes:
            if g["class"] in n:
                n[g["class"]] += 1
        for pid, eb in here.items():
            if pid not in used_p and max((iou(eb, g["bb"]) for g in boxes), default=0) < 0.3:
                ghost += 1
    nt = len(gt["frames"])
    agree = np.mean([red == (t == 0) for red, t in kit_team]) if kit_team else 0.0
    return {
        "player_recall": round((hit["red"] + hit["dark"]) / max(n["red"] + n["dark"], 1), 3),
        "ref_recall": round(hit["referee"] / max(n["referee"], 1), 3),
        "on_other": round(other / nt, 2),
        "ghost": round(ghost / nt, 2),
        "off_px": round(float(np.median(off)), 1) if off else None,
        "team_acc": round(float(max(agree, 1 - agree)), 3),
        **proxies(at, game, d),
    }


def proxies(at, game, game_dir):
    ts = sorted(at)
    ids = sorted({i for fr in at.values() for i in fr})
    life = {}
    for i in ids:
        life[i] = sum(i in at[t] for t in ts) / 10
    tot = sum(life.values()) or 1
    # disappearances > 1 s inside each id's own detections (tracks/ may interpolate them)
    raw = read(f"{game_dir}/_work/players.json")["players"]
    gaps = sum(int((np.diff(p["times"]) > 1.0).sum()) for p in raw)
    return {
        "ids": len(ids),
        "ids_seen5": int(sum((p.get("seen_s") or 0) >= 5 for p in game["players"])),
        "people_per_frame": round(float(np.mean([len(at[t]) for t in ts])), 2),
        "mean_id_life_s": round(float(np.mean(list(life.values()))), 1),
        "life_in_long_ids": round(sum(v for v in life.values() if v >= 30) / tot, 3),
        "gaps_per_id_min": round(gaps / (tot / 60), 2),
        "teams": np.bincount([p["team"] for p in game["players"]]).tolist(),
    }


if __name__ == "__main__":
    doc = read(sys.argv[1])
    for game_dir in sys.argv[2:]:
        print(json.dumps({"game": game_dir, **evaluate(doc, game_dir)}))
