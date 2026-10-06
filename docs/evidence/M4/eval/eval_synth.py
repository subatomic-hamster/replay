"""Score one pipeline run against a synthetic clip's ground truth.

usage: eval_synth.py <clip_dir> <out_dir>   -> prints a JSON metrics dict
Counts (tp, fp, fn) per item so several clips can be summed.
"""

import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
from courtcam.events import _points, _two_pt_zones
from courtcam.pose import iou
from courtcam.profiles import load_profile
from courtcam.schema import Events, Play, Plays, Triggers, read_json
from courtcam.triggers import resolve

clip, out = Path(sys.argv[1]), Path(sys.argv[2])
gt = json.loads((clip / "ground_truth.json").read_text())
W, H, FPS = gt["width"], gt["height"], gt["fps"]
gt_events = json.loads((clip / "events.json").read_text())["events"]
gt_plays = json.loads((clip / "plays.json").read_text())["plays"]
gt_trig = json.loads((clip / "triggers.json").read_text())["triggers"]
profile = load_profile(gt["sport"])
ev = read_json(out / "events.json", Events).events
plays = read_json(out / "plays.json", Plays).plays
trig = read_json(out / "triggers.json", Triggers).triggers

# --- pipeline player id -> GT player id (box IoU votes) ---
frames = {int(f["f"]): f["d"] for f in gt["frames"]}
votes: dict[str, Counter] = {}
for chunk in sorted((out / "tracks").glob("*.json")):
    for fr in json.loads(chunk.read_text())["frames"]:
        rows = frames.get(int(round(fr["t"] * FPS)), [])
        for p in fr["p"]:
            b = (p["bb"][0] * W, p["bb"][1] * H, p["bb"][2] * W, p["bb"][3] * H)
            best = max(rows, key=lambda r: iou(b, tuple(r["bb"])), default=None)
            if best is not None and iou(b, tuple(best["bb"])) > 0.5:
                votes.setdefault(p["id"], Counter())[f"p{best['id']}"] += 1
pid_map = {k: v.most_common(1)[0][0] for k, v in votes.items()}
gt_team = {p["player_id"]: p["team"] for p in gt["players"]}
game = json.loads((out / "game.json").read_text())
tv = Counter()
for p in game["players"]:
    g = pid_map.get(p["id"])
    if g is not None:
        tv[(p["team"], gt_team[g])] += 1
team_map = {}
for (a, b), _ in tv.most_common():
    if a not in team_map and b not in team_map.values():
        team_map[a] = b


def m(pid):
    return pid_map.get(pid) if pid else None


def mt(team):
    return team_map.get(team) if team is not None else None


def match(preds, gts, ok):
    """Greedy one-to-one matching; returns (pairs, unmatched preds, unmatched gts)."""
    used, pairs = set(), []
    for g in gts:
        cands = [
            (abs(cost), k)
            for k, p in enumerate(preds)
            if k not in used and (cost := ok(p, g)) is not None
        ]
        if cands:
            _, k = min(cands)
            used.add(k)
            pairs.append((preds[k], g))
    return pairs, len(preds) - len(used), len(gts) - len(pairs)


def tiou(a0, a1, b0, b1):
    inter = max(0.0, min(a1, b1) - max(a0, b0))
    union = max(a1, b1) - min(a0, b0)
    return inter / union if union > 0 else 0.0


res = {
    "clip": clip.name,
    "sport": gt["sport"],
    "pid_mapped": f"{len(pid_map)}/{len(game['players'])}",
}


def prf(name, pairs, fp, fn, **extra):
    res[name] = {"tp": len(pairs), "fp": fp, "fn": fn, **extra}


# shots: the pipeline's key time is the ball at the rim (GT t_end)
gs = [e for e in gt_events if e["type"] == "shot"]
ps = [e for e in ev if e.type == "shot"]
pairs, fp, fn = match(
    ps, gs, lambda p, g: (p.t_key - g["t_end"]) if abs(p.t_key - g["t_end"]) <= 1.5 else None
)
zones = _two_pt_zones(profile, {"variant": gt["variant"]})
prf(
    "shot", pairs, fp, fn,
    shooter_ok=sum(m(p.player_id) == g["player_id"] for p, g in pairs),
    made_known=sum(p.made is not None for p, _ in pairs),
    made_ok=sum(p.made == g["made"] for p, g in pairs if p.made is not None),
    points_ok=sum(p.points == _points(tuple(g["court"]), zones) for p, g in pairs),
    team_ok=sum(mt(p.team) == g["team"] for p, g in pairs),
)  # fmt: skip

gpc = [e for e in gt_events if e["type"] == "possession_change"]
ppc = [e for e in ev if e.type == "possession_change"]
if gpc or ppc:
    pairs, fp, fn = match(
        ppc,
        gpc,
        lambda p, g: (
            (p.t_key - g["t_key"])
            if abs(p.t_key - g["t_key"]) <= 2.5 and mt(p.team) == g["team"]
            else None
        ),
    )
    prf("possession_change", pairs, fp, fn, cause_ok=sum(p.cause == g["cause"] for p, g in pairs),
        causes=Counter(f"{g['cause']}->{p.cause}" for p, g in pairs))  # fmt: skip

gr = [e for e in gt_events if e["type"] == "rally"]
pr = [e for e in ev if e.type == "rally"]
if gr or pr:
    pairs, fp, fn = match(
        pr,
        gr,
        lambda p, g: (
            (1 - tiou(p.t_start, p.t_end, g["t_start"], g["t_end"]))
            if tiou(p.t_start, p.t_end, g["t_start"], g["t_end"]) >= 0.5
            else None
        ),
    )
    prf(
        "rally",
        pairs,
        fp,
        fn,
        mean_iou=round(
            float(np.mean([tiou(p.t_start, p.t_end, g["t_start"], g["t_end"]) for p, g in pairs])),
            3,
        )
        if pairs
        else None,
    )

gp = [e for e in gt_events if e["type"] == "point"]
pp_ = [e for e in ev if e.type == "point"]
if gp or pp_:
    pairs, fp, fn = match(
        pp_, gp, lambda p, g: (p.t_key - g["t_key"]) if abs(p.t_key - g["t_key"]) <= 1.5 else None
    )
    prf("point", pairs, fp, fn,
        winner_known=sum(p.winner_side is not None for p, _ in pairs),
        winner_ok=sum(mt(p.winner_side) == g["winner_side"] for p, g in pairs if p.winner_side is not None))  # fmt: skip

gc = [e for e in gt_events if e["type"] == "contact"]
pc = [e for e in ev if e.type == "contact"]
if gc or pc:
    pairs, fp, fn = match(
        pc, gc, lambda p, g: (p.t_key - g["t_key"]) if abs(p.t_key - g["t_key"]) <= 0.15 else None
    )
    prf("contact", pairs, fp, fn, hitter_ok=sum(m(p.player_id) == g["player_id"] for p, g in pairs),
        side_ok=sum(mt(p.team) == g["team"] for p, g in pairs))  # fmt: skip

# plays: the sport's primary grammar against GT plays (temporal IoU >= 0.5)
prim = profile.plays[0]["name"] if profile.plays else None
pp = [p for p in plays if p.grammar == prim]
pairs, fp, fn = match(
    pp,
    gt_plays,
    lambda p, g: (
        (1 - tiou(p.t_start, p.t_end, g["t_start"], g["t_end"]))
        if tiou(p.t_start, p.t_end, g["t_start"], g["t_end"]) >= 0.5
        else None
    ),
)
prf("play", pairs, fp, fn, grammar=prim)
play_pairs = {g["id"]: p for p, g in pairs}

# volleyball attack: GT = touch 1,2,3 contacts of one side in a row
if any(p.grammar == "attack" for p in plays) or gt["sport"] == "volleyball":
    seq, gatt = [], []
    for e in [e for e in gt_events if e["type"] == "contact"]:
        if seq and (e["team"] != seq[-1]["team"] or e["t_key"] - seq[-1]["t_key"] > 2.5):
            seq = []
        seq.append(e)
        if len(seq) == 3:
            gatt.append((seq[0]["t_key"], seq[-1]["t_key"]))
            seq = []
    patt = [p for p in plays if p.grammar == "attack"]
    pairs, fp, fn = match(
        patt,
        gatt,
        lambda p, g: (
            (p.t_start - g[0])
            if abs(p.t_start + 0.5 - g[0]) <= 0.5 and abs(p.t_end - 1.0 - g[1]) <= 0.5
            else None
        ),
    )
    prf("attack", pairs, fp, fn)

# triggers per type, then end to end: does the trigger land on the right play?
cfg = profile.triggers
for kind in ("gesture", "voice"):
    g_k = [t for t in gt_trig if t["type"] == kind]
    p_k = [t for t in trig if t.type == kind]
    key = (lambda t: t.t_start) if kind == "gesture" else (lambda t: t.t)
    gkey = (lambda t: t["t_start"]) if kind == "gesture" else (lambda t: t["t"])
    pairs, fp, fn = match(
        p_k,
        g_k,
        lambda p, g, key=key, gkey=gkey: (
            (key(p) - gkey(g)) if abs(key(p) - gkey(g)) <= 1.0 else None
        ),
    )
    extra = {}
    if kind == "gesture":
        extra["by_ok"] = sum(m(p.by_player_id) == g["by_player_id"] for p, g in pairs)
    else:
        extra["subject_needed"] = sum(1 for _, g in pairs if g.get("subject_player_id"))
        extra["subject_ok"] = sum(
            m(p.subject_player_id) == g["subject_player_id"]
            for p, g in pairs
            if g.get("subject_player_id")
        )
        extra["transcripts"] = [p.transcript for p in p_k]
    extra["clip_ok"] = sum(
        1
        for p, g in pairs
        if play_pairs.get(g["play_id"]) is not None
        and (r := resolve(p.t, plays, cfg)) is not None
        and r.id == play_pairs[g["play_id"]].id
    )
    prf(kind, pairs, fp, fn, **extra)
taps = [t for t in gt_trig if t["type"] == "tap"]
res["tap"] = {
    "n": len(taps),
    "clip_ok": sum(
        1
        for g in taps
        if play_pairs.get(g["play_id"]) is not None
        and (r := resolve(g["t"], plays, cfg)) is not None
        and r.id == play_pairs[g["play_id"]].id
    ),
}
# oracle resolution: GT trigger times against GT plays (checks the rule, not detection)
gt_play_objs = [
    Play.model_validate({k: v for k, v in pl.items() if k in Play.model_fields and k != "trigger"})
    for pl in gt_plays
]
res["resolve_rule_on_gt"] = (
    f"{sum(1 for g in gt_trig if (r := resolve(g['t'], gt_play_objs, cfg)) and r.id == g['play_id'])}"
    f"/{len(gt_trig)}"
)
res["counts"] = {
    "events": dict(Counter(e.type for e in ev)),
    "plays": dict(Counter(p.grammar for p in plays)),
    "triggers": dict(Counter(t.type for t in trig)),
}
print(json.dumps(res, default=str))  # ttsr-ignore: py/no-print (CLI output)
