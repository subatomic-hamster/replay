"""Derived stats (plan R1-R4, vision item 26): box score, shot chart, heatmap, distance
covered, and the review queue.

Response shape is D-12 (the plan leaves it unspecified): `box_score`, `shots`, `heatmap`
are exactly what the TV's Review screen renders. M11 adds keys only: per-player points /
misses / unknown outcomes / rebounds / steals / blocks, `available` (which of those the
game's events can support, so the TV hides empty columns), each shot's outcome, points,
team and time, and the `auto-detected` label with the mean event confidence.

All of it is derived from events.json + tracks chunks on read; nothing is precomputed.
A 40-minute game is ~24k track frames — a few hundred ms. ponytail: recompute per
request; cache next to game.json if the TV ever feels it.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Iterable

MIN_HEATMAP_BINS = 4  # a 6.1 m wide pickleball court still wants a usable grid
SMOOTH_WIN = 5  # track samples (10 Hz -> 0.5 s) for distance covered
MAX_SPEED_MPS = 9.0  # faster than any sprint: an id switch / foot-point jump, not running
MAX_GAP_S = 0.5  # a longer absence breaks the path (no straight line across a re-entry)
REVIEW_CONFIDENCE = 0.6  # tv-core REVIEW_CONFIDENCE_THRESHOLD
IDENTITY_QUESTIONS = 5


def _heatmap_bins(x_range: list[float], y_range: list[float]) -> tuple[int, int]:
    """~1 m square cells, from the court's own extents.

    Was hardcoded (15, 14) — a FIBA half court — so every net sport binned a 6.1 x 13.4 m
    court into basketball's grid and drew 2.5:1 cells over the wrong ranges. The TV reads
    `cols`/`rows` off the response, so nothing downstream assumes the counts.
    """
    return (
        max(MIN_HEATMAP_BINS, round(x_range[1] - x_range[0])),
        max(MIN_HEATMAP_BINS, round(y_range[1] - y_range[0])),
    )


def _court_ranges(profile: dict | None) -> tuple[list[float], list[float]]:
    court = (profile or {}).get("court") or {}
    return (
        [float(v) for v in court.get("x_range", [-7.5, 7.5])],
        [float(v) for v in court.get("y_range", [0.0, 14.0])],
    )


def _moving_average(pts: list[tuple[float, float]], win: int) -> list[tuple[float, float]]:
    if len(pts) < win or win < 2:
        return pts
    out = []
    half = win // 2
    for i in range(len(pts)):
        lo, hi = max(0, i - half), min(len(pts), i + half + 1)
        chunk = pts[lo:hi]
        out.append((sum(p[0] for p in chunk) / len(chunk), sum(p[1] for p in chunk) / len(chunk)))
    return out


def distance_covered(path: list[tuple[float, float, float]]) -> tuple[float, int]:
    """(metres, samples dropped) along (t, x, y) samples: a sample reached faster than
    MAX_SPEED_MPS from the last kept one is dropped as a jump, an absence over MAX_GAP_S
    starts a new run, and each run is smoothed (SMOOTH_WIN) before summing."""
    runs: list[list[tuple[float, float]]] = []
    last: tuple[float, float, float] | None = None
    dropped = 0
    for t, x, y in path:
        if last is not None and t - last[0] <= MAX_GAP_S:
            if math.dist((x, y), last[1:]) > MAX_SPEED_MPS * max(t - last[0], 1e-3):
                dropped += 1
                continue
            runs[-1].append((x, y))
        else:
            runs.append([(x, y)])
        last = (t, x, y)
    total = sum(
        math.dist(a, b)
        for run in runs
        for a, b in itertools.pairwise(_moving_average(run, SMOOTH_WIN))
    )
    return total, dropped


def _confidence(e: dict) -> float:
    """A user-verified event (`confirmed`, e.g. a review "Yes") counts as certain."""
    return 1.0 if e.get("confirmed") else float(e.get("confidence") or 0.0)


def _outcome(e: dict) -> str:
    made = e.get("made")
    return "make" if made is True else "miss" if made is False else "unknown"


def compute(game: dict, events: list[dict], frames: Iterable[dict], profile: dict | None) -> dict:
    players = game.get("players") or []
    x_range, y_range = _court_ranges(profile)
    nx, ny = _heatmap_bins(x_range, y_range)

    grids = {p["id"]: [[0] * nx for _ in range(ny)] for p in players}
    paths: dict[str, list[tuple[float, float, float]]] = {p["id"]: [] for p in players}

    for frame in frames:
        t = float(frame.get("t") or 0.0)
        for entry in frame.get("p", []):
            pid, ct = entry.get("id"), entry.get("ct")
            if pid not in grids or not ct:
                continue
            x, y = float(ct[0]), float(ct[1])
            paths[pid].append((t, x, y))
            ix = int((x - x_range[0]) / max(1e-9, x_range[1] - x_range[0]) * nx)
            iy = int((y - y_range[0]) / max(1e-9, y_range[1] - y_range[0]) * ny)
            if 0 <= ix < nx and 0 <= iy < ny:
                grids[pid][iy][ix] += 1

    shots = [e for e in events if e.get("type") == "shot"]
    rebounds = [e for e in events if e.get("cause") == "defensive_rebound"]
    steals = [
        e for e in events if e.get("type") == "possession_change" and e.get("cause") == "steal"
    ]
    blocks = [e for e in events if e.get("type") == "block"]
    available = [
        k
        for k, evs in (
            ("shots", shots),
            ("rebounds", rebounds),
            ("steals", steals),
            ("blocks", blocks),
        )
        if evs
    ]

    def count(evs: list[dict], pid: str) -> int:
        return sum(1 for e in evs if e.get("player_id") == pid)

    rows = []
    heatmap = []
    for p in players:
        pid = p["id"]
        mine = [e for e in shots if e.get("player_id") == pid]
        makes = [e for e in mine if e.get("made") is True]
        confidences = [_confidence(e) for e in mine]
        dist, dropped = distance_covered(paths[pid])
        rows.append(
            {
                "player_id": pid,
                "name": p.get("name"),
                "team": p.get("team"),
                "attempts": len(mine),
                "makes": len(makes),
                "misses": sum(1 for e in mine if e.get("made") is False),
                "unknown": sum(1 for e in mine if e.get("made") is None),
                # a make without a detected value counts 2 (gamedata.score_from_events)
                "points": sum(int(e.get("points") or 2) for e in makes),
                "threes": sum(1 for e in makes if e.get("points") == 3),
                "rebounds": count(rebounds, pid),
                "steals": count(steals, pid),
                "blocks": count(blocks, pid),
                "confirmed": sum(1 for e in mine if e.get("confirmed")),
                "confidence": (
                    round(sum(confidences) / len(confidences), 2) if confidences else 0.0
                ),
                "distance_m": round(dist, 1),
                "distance_dropped": dropped,
                "samples": len(paths[pid]),
            }
        )
        heatmap.append(
            {
                "player_id": pid,
                "cols": nx,
                "rows": ny,
                "x_range": x_range,
                "y_range": y_range,
                # row-major, cols * rows values
                "values": [v for row in grids[pid] for v in row],
            }
        )

    used = shots + rebounds + steals + blocks
    return {
        "schema": "replay.stats.v1",
        "game_id": game["id"],
        # R3: stats are always presented as auto-detected; user confirmations count too.
        "auto_detected": True,
        "label": "auto-detected",
        "confidence": (round(sum(_confidence(e) for e in used) / len(used), 2) if used else None),
        # additive: how many of the counted events a person verified (review answers)
        "confirmed": sum(1 for e in used if e.get("confirmed")),
        "available": available,
        "box_score": rows,
        "shots": [
            {
                "event_id": e["id"],
                "player_id": e.get("player_id"),
                "team": e.get("team"),
                "t": e.get("t_key"),
                "court": e.get("court"),
                "made": bool(e.get("made")),
                "outcome": _outcome(e),
                "points": e.get("points"),
                "confirmed": bool(e.get("confirmed")),
                "confidence": e.get("confidence"),
            }
            for e in shots
            if e.get("court")
        ],
        "heatmap": heatmap,
        "totals": {
            "attempts": len(shots),
            "makes": sum(1 for e in shots if e.get("made")),
        },
    }


def review_queue(game: dict, events: list[dict], frames: Iterable[dict]) -> list[dict]:
    """Questions a viewer can answer with the remote, most useful first. Each option is
    the existing PATCH it maps to, so answering needs no new write path:
    shot outcomes the detector could not tell, low-confidence events (R5), and who the
    most-seen untagged players are (name them, or merge into a tagged player)."""
    gid = game["id"]
    out: list[dict] = []
    for e in sorted(events, key=lambda e: e.get("t_key") or 0.0):
        if e.get("confirmed") or e.get("type") not in ("shot", "block", "possession_change"):
            continue
        path = f"/games/{gid}/events/{e['id']}"
        conf = float(e.get("confidence") or 0.0)
        q = {"event_id": e["id"], "t": e.get("t_key"), "player_id": e.get("player_id")}
        q["confidence"] = conf
        no = _opt("Not a shot", "PATCH", path, {"dismissed": True, "confirmed": True})
        if e["type"] == "shot" and e.get("made") is None:
            q.update(id=f"q_outcome_{e['id']}", kind="shot_outcome", prompt="Make or miss?")
            q["options"] = [
                _opt("Made", "PATCH", path, {"made": True, "confirmed": True}),
                _opt("Missed", "PATCH", path, {"made": False, "confirmed": True}),
                no,
            ]
        elif conf < REVIEW_CONFIDENCE:
            noun = {"shot": "a shot", "block": "a block"}.get(e["type"], "a change of possession")
            q.update(id=f"q_conf_{e['id']}", kind="low_confidence", prompt=f"Was this {noun}?")
            q["options"] = [_opt("Yes", "PATCH", path, {"confirmed": True}), {**no, "label": "No"}]
        else:
            continue
        out.append(q)
    # identity: untagged players, most seen first, shown where their box is largest
    best: dict[str, tuple[float, float, int]] = {}  # pid -> (box h, t, samples)
    for frame in frames:
        for entry in frame.get("p", []):
            pid, bb = entry.get("id"), entry.get("bb")
            if not pid or not bb:
                continue
            h, t, n = best.get(pid, (0.0, 0.0, 0))
            best[pid] = (bb[3], frame["t"], n + 1) if bb[3] > h else (h, t, n + 1)
    players = game.get("players") or []
    tagged = [p for p in players if p.get("name")]
    untagged = sorted(
        (p for p in players if not p.get("name") and p["id"] in best),
        key=lambda p: -best[p["id"]][2],
    )
    for p in untagged[:IDENTITY_QUESTIONS]:
        path = f"/games/{gid}/players/{p['id']}"
        mates = [q for q in tagged if q.get("team") == p.get("team")] or tagged
        out.append(
            {
                "id": f"q_who_{p['id']}",
                "kind": "identity",
                "player_id": p["id"],
                "t": best[p["id"]][1],
                "samples": best[p["id"]][2],
                "prompt": f"Who is #{p['id']}?",
                "options": [
                    _opt("Type a name", "PATCH", path, {}, text_field="name"),
                    *(
                        _opt(f"Same as {q['name']}", "PATCH", path, {"merge_into": q["id"]})
                        for q in mates
                    ),
                ],
            }
        )
    return out


def _opt(label: str, method: str, path: str, body: dict, text_field: str | None = None) -> dict:
    opt = {"label": label, "method": method, "path": path, "body": body}
    if text_field:
        opt["text_field"] = text_field  # the client fills body[text_field] from a keyboard
    return opt
