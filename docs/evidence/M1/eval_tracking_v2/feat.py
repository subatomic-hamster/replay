"""Which link cues pick the right successor? (synthetic GT only)
usage: feat.py <clip_dir> <out_dir>
For each court tracklet `a` whose true successor (next tracklet with the same majority
GT id) is among its same-team candidates (gap -1..5 s), the share of `a` for which a cue
ranks that successor first.
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from courtcam.court import CourtTrack, read_court_tracks
from courtcam.identity import app_distance, assign_teams, sample_appearance
from courtcam.metrics import _assign, iou_matrix
from courtcam.profiles import load_profile
from courtcam.track import Tracklet

clip, out = Path(sys.argv[1]), Path(sys.argv[2])
truth = json.loads((clip / "ground_truth.json").read_text())
gall = {
    int(fr["f"]): [(d["id"], d["bb"]) for d in fr["d"] if d["oncourt"]] for fr in truth["frames"]
}
ct, _ = read_court_tracks(out / "_work" / "court.json")
prof = load_profile(truth["sport"])
video = str(out / "media/wide.mp4")
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


def ends(c, first):  # GT id at the first / last labelled sample
    fr = c.tracklet.frames.tolist()
    for f in fr if first else fr[::-1]:
        if (c.track_id, f) in lab:
            return lab[(c.track_id, f)]
    return -1


def cut(c, head_):  # first / last 2 s of a tracklet
    t = c.tracklet
    k = (t.times <= t.times[0] + 2.0) if head_ else (t.times >= t.times[-1] - 2.0)
    return CourtTrack(
        Tracklet(t.track_id, t.frames[k], t.times[k], t.boxes[k], t.confs[k]), c.court_m[k], 1.0
    )


def vel(c, at_end):
    t, p = c.tracklet.times, c.court_m
    k = (t >= t[-1] - 0.5) if at_end else (t <= t[0] + 0.5)
    tt, pp = t[k], p[k]
    if len(tt) < 2 or tt[-1] - tt[0] < 0.2:
        return np.zeros(2)
    v = (pp[-1] - pp[0]) / (tt[-1] - tt[0])
    n = np.linalg.norm(v)
    return v if n < 8 else v * 8 / n


head = [ends(c, True) for c in ct]
tail = [ends(c, False) for c in ct]
hists, colors, body = sample_appearance(video, ct)
teams = assign_teams(hists, ct, prof, prof.template(truth["variant"]))
_, _, body_h = sample_appearance(video, [cut(c, True) for c in ct])
_, _, body_t = sample_appearance(video, [cut(c, False) for c in ct])
S = np.array([c.tracklet.t_start for c in ct])
E = np.array([c.tracklet.t_end for c in ct])
# relative stature: box height over a linear fit of height on foot y
allb = np.vstack([c.tracklet.boxes for c in ct])
fit = np.polyfit(allb[:, 1] + allb[:, 3], allb[:, 3], 1)
stat = np.array(
    [
        np.median(
            c.tracklet.boxes[:, 3]
            / np.polyval(fit, c.tracklet.boxes[:, 1] + c.tracklet.boxes[:, 3])
        )
        for c in ct
    ]
)

cues = defaultdict(list)
for a, ca in enumerate(ct):
    gap = S - E[a]
    cand = np.flatnonzero((gap >= -1) & (gap <= 5) & (E > E[a]) & (teams == teams[a]))
    true = [b for b in cand if head[b] == tail[a] and tail[a] > 0]
    if not true or len(cand) < 2:
        continue
    true = min(true, key=lambda b: S[b])
    va = vel(ca, True)
    f = defaultdict(dict)
    for b in cand:
        g = gap[b]
        here = ca.court_at(S[b]) if g < 0 else ca.court_m[-1]
        st = ct[b].court_m[0]
        gp = max(g, 0)
        d_end = np.linalg.norm(st - here)
        d_mid = np.linalg.norm((here + va * gp / 2) - (st - vel(ct[b], False) * gp / 2))
        f["d_end"][b] = d_end
        f["d_pred"][b] = np.linalg.norm(st - (here + va * gp))
        f["d_mid"][b] = d_mid
        f["end_norm"][b] = d_end / (1 + 3 * gp) + 0.3 * gp
        f["app"][b] = app_distance(body[a], body[b])
        f["app_ends"][b] = app_distance(body_t[a], body_h[b])
        f["stat"][b] = abs(stat[a] - stat[b])
    for k, d in f.items():
        cues[k].append(min(d, key=d.get) == true)
print(
    json.dumps(
        {
            "clip": clip.name,
            "n": len(cues["d_end"]),
            **{k: round(float(np.mean(v)), 3) for k, v in cues.items()},
        }
    )
)  # ttsr-ignore: py/no-print (CLI output)
