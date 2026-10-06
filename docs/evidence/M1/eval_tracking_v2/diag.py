"""Where do player identities break? (synthetic GT only)
usage: diag.py <clip_dir> <out_dir>

Labels every raw tracklet sample and every player sample with the GT id it overlaps
(IoU >= 0.5, Hungarian per frame, on-court GT only), then counts:
  * tracklet impurity: tracklets that carry >1 GT id (internal switch), same vs cross team
  * merge errors: consecutive members of one player whose majority GT ids differ
    (only meaningful on runs at HEAD: after splitting, members repeat track ids)
  * fragmentation: players per GT id
"""

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from courtcam.court import read_court_tracks
from courtcam.identity import read_players
from courtcam.metrics import _assign, iou_matrix
from courtcam.track import read_tracklets

clip, out = Path(sys.argv[1]), Path(sys.argv[2])
truth = json.loads((clip / "ground_truth.json").read_text())
team_of = {p["id"]: p["team"] for p in truth["players"]}
gt = {int(fr["f"]): [(d["id"], d["bb"]) for d in fr["d"] if d["oncourt"]] for fr in truth["frames"]}


def label(rows):  # rows: {frame: [(key, box)]} -> {(key, frame): gt id}
    lab = {}
    for f, rs in rows.items():
        g = gt.get(f, [])
        if not g or not rs:
            continue
        m = iou_matrix(np.array([b for _, b in g]), np.array([b for _, b in rs]))
        for a, b in _assign(m, 0.5):
            lab[(rs[b][0], f)] = g[a][0]
    return lab


def seqs(items):  # items: [(key, frames, boxes)] -> {key: [gt id or -1 per sample]}
    rows = defaultdict(list)
    for k, fr, bx in items:
        for f, b in zip(fr.tolist(), bx.tolist(), strict=True):
            rows[int(f)].append((k, b))
    lab = label(rows)
    return {k: [lab.get((k, int(f)), -1) for f in fr] for k, fr, _ in items}


def impurity(name, items):
    s = seqs(items)
    multi = same = cross = wrong = tot = 0
    for lab in s.values():
        lab = [x for x in lab if x > 0]
        if not lab:
            continue
        c = Counter(lab)
        tot += len(lab)
        wrong += len(lab) - c.most_common(1)[0][1]
        runs = []  # a switch = the GT id changes and the new one holds >= 5 samples
        for x in lab:
            if runs and runs[-1][0] == x:
                runs[-1][1] += 1
            else:
                runs.append([x, 1])
        runs = [r for r in runs if r[1] >= 5]
        sw = [(a[0], b[0]) for a, b in zip(runs, runs[1:]) if a[0] != b[0]]
        multi += bool(sw)
        for a, b in sw:
            same += team_of[a] == team_of[b]
            cross += team_of[a] != team_of[b]
    return {
        f"{name}_n": len(s),
        f"{name}_with_switch": multi,
        f"{name}_switch_same_team": same,
        f"{name}_switch_cross_team": cross,
        f"{name}_wrong_frame_frac": round(wrong / max(tot, 1), 3),
    }


tl, _ = read_tracklets(out / "_work" / "tracklets.json")
ct, _ = read_court_tracks(out / "_work" / "court.json")
pl, _ = read_players(out / "_work" / "players.json")
rep = {"clip": clip.name}
rep |= impurity("raw_tracklet", [(t.track_id, t.frames, t.boxes) for t in tl])
rep |= impurity("court_tracklet", [(c.track_id, c.tracklet.frames, c.tracklet.boxes) for c in ct])
rep |= impurity(
    "player", [(p.player_id, p.track.tracklet.frames, p.track.tracklet.boxes) for p in pl]
)

s = seqs([(c.track_id, c.tracklet.frames, c.tracklet.boxes) for c in ct])
maj = {
    k: Counter(x for x in v if x > 0).most_common(1)[0][0] if any(x > 0 for x in v) else -1
    for k, v in s.items()
}
good = bad_same = bad_cross = 0
for p in pl:
    m = [maj.get(i, -1) for i in p.members]
    for a, b in zip(m, m[1:]):
        if a < 0 or b < 0:
            continue
        good += a == b
        bad_same += a != b and team_of[a] == team_of[b]
        bad_cross += team_of[a] != team_of[b]
rep |= {"links_right": good, "links_wrong_same_team": bad_same, "links_wrong_cross_team": bad_cross}
used = {i for p in pl for i in p.members}
rep["candidates_dropped"] = sum(c.track_id not in used for c in ct)
rep["players"] = len(pl)
print(json.dumps(rep))  # ttsr-ignore: py/no-print (CLI output)
