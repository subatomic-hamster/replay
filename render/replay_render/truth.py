"""Synthetic-only: a copy of a processed game whose events / score / plays / roster names
come from the generator's ground truth instead of the detectors.

This exists to exercise the graphics package (score bug changes, lower thirds with
names, replays of makes) while the make/miss detector is still being built. Everything
it writes is labelled `"source": "synthetic_ground_truth"`; tracks, crops, calibration
and video stay the pipeline's own. Ground-truth player ids are mapped to pipeline ids
by box overlap (the synthetic detector replays ground-truth boxes).
"""

from __future__ import annotations

import json
import shutil
from collections import Counter
from pathlib import Path

import numpy as np

from .gamedata import load_tracks, read_json

LABEL = "synthetic_ground_truth"


def id_map(truth: dict, game_dir: Path, width: int, height: int) -> dict[str, str]:
    """Ground-truth player_id -> pipeline player id, by nearest box centre (vote)."""
    tr = load_tracks(game_dir, width, height)
    gt_pid = {p["id"]: p["player_id"] for p in truth["players"]}
    votes: dict[str, Counter] = {}
    centres = np.stack(
        [(tr.box[..., 0] + tr.box[..., 2]) / 2, (tr.box[..., 1] + tr.box[..., 3]) / 2], -1
    )
    for fr in truth["frames"][::15]:
        j = int(np.argmin(np.abs(tr.t - fr["t"])))
        if abs(tr.t[j] - fr["t"]) > 0.06:
            continue
        for row in fr["d"]:
            if row["id"] not in gt_pid or row.get("vis", 1.0) < 0.6:
                continue
            x, y, w, h = row["bb"]
            d = np.linalg.norm(centres[:, j] - [x + w / 2, y + h / 2], axis=1)
            if np.isfinite(d).any() and np.nanmin(d) < max(w, h):
                votes.setdefault(gt_pid[row["id"]], Counter())[tr.ids[int(np.nanargmin(d))]] += 1
    return {g: c.most_common(1)[0][0] for g, c in votes.items()}


def write_truth_game(game_dir: Path, truth_dir: Path, out_dir: Path) -> dict:
    gd, td, od = Path(game_dir), Path(truth_dir), Path(out_dir)
    if od.exists():
        shutil.rmtree(od)
    shutil.copytree(gd, od, ignore=shutil.ignore_patterns("media", "_work", "poses", "audio"))
    (od / "media").mkdir()
    (od / "media" / "wide.mp4").symlink_to((gd / "media" / "wide.mp4").resolve())
    game = read_json(gd / "game.json")
    truth = read_json(td / "ground_truth.json")
    pmap = id_map(truth, gd, game["video"]["width"], game["video"]["height"])
    names = {pmap[p["player_id"]]: p["name"] for p in truth["players"] if p["player_id"] in pmap}
    teams_gt = {p["player_id"]: p["team"] for p in truth["players"]}
    # pipeline team ids are jersey clusters; align them with the ground-truth teams
    team_votes = Counter(
        (teams_gt[g], next((p["team"] for p in game["players"] if p["id"] == pid), None))
        for g, pid in pmap.items()
    )
    flip = team_votes[(0, 1)] + team_votes[(1, 0)] > team_votes[(0, 0)] + team_votes[(1, 1)]
    for p in game["players"]:
        if p["id"] in names:
            p["name"], p["tagged"] = names[p["id"]], True
    game["title"] = f"{game.get('title', '')} (synthetic; events from ground truth)"
    (od / "game.json").write_text(json.dumps(game, indent=1))

    def team(t: int | None) -> int | None:
        return None if t is None else (1 - t if flip else t)

    events, score, a = [], [], [0, 0]
    for e in read_json(td / "events.json")["events"]:
        ev = {**e, "source": "user", "provenance": LABEL, "confidence": 1.0}
        for k in ("player_id", "receiver_id"):
            if ev.get(k):
                ev[k] = pmap.get(ev[k])
        ev["team"] = team(e.get("team"))
        if e["type"] == "shot":
            ev["points"] = ev.get("points") or (3 if np.hypot(*_rel_rim(e["court"])) > 6.75 else 2)
            if e.get("made") and ev["team"] in (0, 1):
                a[ev["team"]] += ev["points"]
                score.append({"t": e["t_key"], "scores": list(a), "event_id": e["id"],
                              "source": "user"})  # fmt: skip
        events.append(ev)
    (od / "events.json").write_text(json.dumps(
        {"schema": "replay.events.v1", "provenance": LABEL, "events": events}, indent=1))  # fmt: skip
    (od / "score.json").write_text(json.dumps(
        {"schema": "replay.score.v1", "provenance": LABEL, "score": score}, indent=1))  # fmt: skip
    (od / "plays.json").write_text(json.dumps(
        {"schema": "replay.plays.v1", "provenance": LABEL, "plays": []}))  # fmt: skip
    return {"id_map": pmap, "teams_flipped": flip, "makes": len(score), "final": a}


def _rel_rim(court: list[float]) -> tuple[float, float]:
    """Offset from the nearer FIBA rim (0, 1.575) / (0, 26.425), for the 2-vs-3 call."""
    x, y = court
    ry = 1.575 if y < 14 else 26.425
    return x, y - ry
