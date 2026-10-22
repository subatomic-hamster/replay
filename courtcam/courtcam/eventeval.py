"""Score a game's detected events against a hand annotation (`courtcam eval-events`, D-90).

The truth is a `replay.playlog.v1` file with `use: evaluation` (samples/truth/*.json). It
is only ever read here: nothing in the pipeline imports this module or those files, so no
detector can see the answers.

Matching: a detected shot matches a counted truth shot when its `t_key` (the ball at the
rim) is within `tol_s` of the truth's `t_rim` (else its release + 1 s); greedy, closest
first, one to one. A detection that matches a shot the annotation marks `counts: false`
(after the whistle, fouled and missed) is neither right nor wrong. Pipeline teams are 0/1
by jersey colour, truth teams are names: the team mapping is the one that agrees with
more matched shots (ties: the one with the smaller score error), and is reported.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .playlog import PlayEntry, PlayLog

NOTABLE = ("block", "steal")


@dataclass
class Match:
    truth: PlayEntry
    pred: dict[str, Any]
    dt: float


def _ref(e: PlayEntry) -> float:
    return e.t_rim if e.t_rim is not None else e.t + 1.0


def match_shots(pred: list[dict], truth: list[PlayEntry], tol_s: float):
    """(matches, unmatched preds, unmatched truth) — greedy on |dt|."""
    pairs = sorted(
        (abs(float(p["t_key"]) - _ref(t)), i, j)
        for i, p in enumerate(pred)
        for j, t in enumerate(truth)
        if abs(float(p["t_key"]) - _ref(t)) <= tol_s
    )
    used_p: set[int] = set()
    used_t: set[int] = set()
    out = []
    for dt, i, j in pairs:
        if i in used_p or j in used_t:
            continue
        used_p.add(i)
        used_t.add(j)
        out.append(Match(truth[j], pred[i], dt))
    return (
        sorted(out, key=lambda m: _ref(m.truth)),
        [p for i, p in enumerate(pred) if i not in used_p],
        [t for j, t in enumerate(truth) if j not in used_t],
    )


def _ratio(a: int, b: int) -> float | None:
    return round(a / b, 3) if b else None


def _final(score: list[dict]) -> list[int]:
    return list(score[-1]["scores"]) if score else [0, 0]


def evaluate(
    events: list[dict],
    truth: PlayLog,
    *,
    score: list[dict] | None = None,
    hype: dict | None = None,
    tol_s: float = 1.5,
    top_k: int = 5,
) -> dict[str, Any]:
    events = [e for e in events if not e.get("dismissed")]
    shots = sorted((e for e in events if e.get("type") == "shot"), key=lambda e: e["t_key"])
    counted = truth.shots(counted=True)
    ignored = [e for e in truth.shots(counted=False) if not e.counts]
    m, fp, fn = match_shots(shots, counted, tol_s)
    # detections of non-counting shots are neutral
    m_ign, fp, _ = match_shots(fp, ignored, tol_s)
    tp = len(m)

    teams = sorted({e.team for e in truth.entries if e.team})
    names = (teams + ["?", "?"])[:2]

    def agree(mapping: dict[int, str]) -> int:
        return sum(mapping.get(x.pred.get("team")) == x.truth.team for x in m)

    maps = [{0: names[0], 1: names[1]}, {0: names[1], 1: names[0]}]
    # truth points scored inside the clip, per team name
    t_pts = {n: 0 for n in names}
    for e in counted:
        if e.made and e.points and e.team in t_pts:
            t_pts[e.team] += e.points
    final = _final(score or [])

    def score_err(mapping: dict[int, str]) -> int:
        return sum(abs(final[k] - t_pts.get(mapping[k], 0)) for k in (0, 1))

    mapping = max(maps, key=lambda mp: (agree(mp), -score_err(mp)))
    known = [x for x in m if x.pred.get("made") is not None and x.truth.made is not None]
    made_pred = [s for s in shots if s.get("made") is True]
    made_tp = [x for x in m if x.pred.get("made") is True and x.truth.made is True]
    made_truth = [e for e in counted if e.made]
    pts_ok = [x for x in made_tp if x.pred.get("points") == x.truth.points]
    ft_truth = [x for x in m if x.truth.type == "free_throw"]

    out: dict[str, Any] = {
        "truth": {
            "shots": len(counted),
            "makes": len(made_truth),
            "points": t_pts,
            "not_counted": len(ignored),
        },  # fmt: skip
        "shots": {
            "detected": len(shots),
            "tp": tp,
            "fp": len(fp),
            "fn": len(fn),
            "neutral": len(m_ign),
            "precision": _ratio(tp, tp + len(fp)),
            "recall": _ratio(tp, tp + len(fn)),
            "mean_abs_dt_s": round(sum(x.dt for x in m) / tp, 2) if tp else None,
            "free_throws_found": f"{len(ft_truth)}/{sum(e.type == 'free_throw' for e in counted)}",
        },
        "make_miss": {
            "labelled": f"{len(known)}/{tp}",
            "accuracy": _ratio(sum(x.pred["made"] == x.truth.made for x in known), len(known)),
            "make_precision": _ratio(len(made_tp), len(made_pred)),
            "make_recall": _ratio(len(made_tp), len(made_truth)),
        },
        "points": {"made_with_right_points": f"{len(pts_ok)}/{len(made_tp)}"},
        "team": {
            "mapping": {str(k): v for k, v in mapping.items()},
            "agree": f"{agree(mapping)}/{tp}",
        },  # fmt: skip
        "score": {
            "truth": {mapping[0]: t_pts.get(mapping[0], 0), mapping[1]: t_pts.get(mapping[1], 0)},
            "pipeline": {mapping[0]: final[0], mapping[1]: final[1]},
            "abs_error": score_err(mapping),
        },
        "misses_detail": {
            "fn": [{"t": e.t, "t_rim": e.t_rim, "type": e.type, "made": e.made} for e in fn],
            "fp": [{"t_key": p["t_key"], "made": p.get("made")} for p in fp],
            "wrong_make": [
                {"t_rim": _ref(x.truth), "truth": x.truth.made, "pred": x.pred.get("made")}
                for x in known
                if x.pred["made"] != x.truth.made
            ],
        },
    }
    if hype is not None:
        out["highlights"] = highlights(hype, truth, top_k)
    return out


def highlights(hype: dict, truth: PlayLog, k: int) -> dict[str, Any]:
    """Do the top-k highlight candidates (hype.json, best first) hold real notable plays?
    Notable = a made field goal, a block, a steal. Precision@k: candidates whose window
    (±1 s) holds one; recall: made field goals inside some top-k window."""
    cands = (hype.get("candidates") or [])[:k]
    notable = [e for e in truth.entries if (e.type == "shot" and e.made and e.counts)
               or e.type in NOTABLE]  # fmt: skip
    makes = [e for e in truth.entries if e.type == "shot" and e.made and e.counts]

    def inside(e: PlayEntry, c: dict) -> bool:
        return c.get("t_start", c["t"]) - 1.0 <= e.t <= c.get("t_end", c["t"]) + 1.0

    hit = sum(any(inside(e, c) for e in notable) for c in cands)
    got = sum(any(inside(e, c) for c in cands) for e in makes)
    return {
        "candidates": len(hype.get("candidates") or []),
        "top_k": len(cands),
        "precision_at_k": _ratio(hit, len(cands)),
        "fg_makes_in_top_k": f"{got}/{len(makes)}",
        "top": [
            {
                "t": c["t"],
                "t_start": c.get("t_start"),
                "t_end": c.get("t_end"),
                "reasons": c.get("reasons"),
            }
            for c in cands
        ],  # fmt: skip
    }


def evaluate_dir(game_dir: Path, truth: PlayLog, *, events_path: Path | None = None,
                 tol_s: float = 1.5, top_k: int = 5) -> dict[str, Any]:  # fmt: skip
    gd = Path(game_dir)

    def read(name: str, key: str | None = None):
        p = gd / name
        if not p.is_file():
            return None
        doc = json.loads(p.read_text(encoding="utf-8"))
        return doc.get(key) if key else doc

    events = json.loads(Path(events_path or gd / "events.json").read_text())["events"]
    score = read("score.json", "score")
    if events_path is not None or score is None:
        from .plays import score_timeline
        from .schema import Event

        score = [s.model_dump() for s in score_timeline([Event.model_validate(e) for e in events])]
    return evaluate(events, truth, score=score, hype=read("hype.json"), tol_s=tol_s, top_k=top_k)


def report(r: dict[str, Any]) -> str:
    """The numbers as a few lines of text."""
    s, mm = r["shots"], r["make_miss"]
    lines = [
        f"truth: {r['truth']['shots']} shots, {r['truth']['makes']} makes, "
        f"points {r['truth']['points']}",
        f"shots: detected {s['detected']}, P {s['precision']} R {s['recall']} "
        f"(tp {s['tp']} fp {s['fp']} fn {s['fn']} neutral {s['neutral']}), "
        f"|dt| {s['mean_abs_dt_s']} s, free throws {s['free_throws_found']}",
        f"make/miss: labelled {mm['labelled']}, accuracy {mm['accuracy']}, "
        f"makes P {mm['make_precision']} R {mm['make_recall']}",
        f"points: {r['points']['made_with_right_points']}; team agree {r['team']['agree']} "
        f"(map {r['team']['mapping']})",
        f"score: truth {r['score']['truth']} pipeline {r['score']['pipeline']} "
        f"abs error {r['score']['abs_error']}",
    ]
    if "highlights" in r:
        h = r["highlights"]
        lines.append(
            f"highlights: {h['candidates']} candidates, P@{h['top_k']} {h['precision_at_k']}, "
            f"FG makes in top {h['fg_makes_in_top_k']}"
        )
    return "\n".join(lines)
