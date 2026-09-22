"""Derived stats (plan R1–R4): box score lite, shot chart, heatmap, distance covered.

All of it is derived from events.json + tracks chunks on read; nothing is precomputed.
A 40-minute game is ~24k track frames — a few hundred ms. ponytail: recompute per
request; cache next to game.json if the TV ever feels it.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Iterable

HEATMAP_BINS = (15, 14)  # x, y — one bin per court metre on a FIBA half court
SMOOTH_WIN = 5  # track samples (10 Hz -> 0.5 s) for distance covered


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


def compute(game: dict, events: list[dict], frames: Iterable[dict], profile: dict | None) -> dict:
    players = game.get("players") or []
    x_range, y_range = _court_ranges(profile)
    nx, ny = HEATMAP_BINS

    grids = {p["id"]: [[0] * nx for _ in range(ny)] for p in players}
    paths: dict[str, list[tuple[float, float]]] = {p["id"]: [] for p in players}

    for frame in frames:
        for entry in frame.get("p", []):
            pid, ct = entry.get("id"), entry.get("ct")
            if pid not in grids or not ct:
                continue
            x, y = float(ct[0]), float(ct[1])
            paths[pid].append((x, y))
            ix = int((x - x_range[0]) / max(1e-9, x_range[1] - x_range[0]) * nx)
            iy = int((y - y_range[0]) / max(1e-9, y_range[1] - y_range[0]) * ny)
            if 0 <= ix < nx and 0 <= iy < ny:
                grids[pid][iy][ix] += 1

    shots = [e for e in events if e.get("type") == "shot"]
    rows = []
    for p in players:
        pid = p["id"]
        mine = [e for e in shots if e.get("player_id") == pid]
        smoothed = _moving_average(paths[pid], SMOOTH_WIN)
        distance = sum(math.dist(a, b) for a, b in itertools.pairwise(smoothed))
        rows.append(
            {
                "id": pid,
                "name": p.get("name"),
                "team": p.get("team"),
                "attempted": len(mine),
                "made": sum(1 for e in mine if e.get("made")),
                "confirmed": sum(1 for e in mine if e.get("confirmed")),
                "distance_m": round(distance, 1),
                "samples": len(paths[pid]),
                "heatmap": {
                    "bins": [nx, ny],
                    "x_range": x_range,
                    "y_range": y_range,
                    "grid": grids[pid],
                },
            }
        )

    shot_chart = [
        {
            "event_id": e["id"],
            "player_id": e.get("player_id"),
            "court": e.get("court"),
            "made": bool(e.get("made")),
            "confidence": e.get("confidence"),
            "auto_detected": e.get("auto_detected", e.get("source") != "user"),
        }
        for e in shots
        if e.get("court")
    ]

    return {
        "schema": "replay.stats.v1",
        "game_id": game["id"],
        # R3: stats are always presented as auto-detected; user confirmations count too.
        "auto_detected": True,
        "players": rows,
        "shot_chart": shot_chart,
        "totals": {
            "attempted": len(shots),
            "made": sum(1 for e in shots if e.get("made")),
        },
    }
