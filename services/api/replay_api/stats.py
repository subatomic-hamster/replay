"""Derived stats (plan R1-R4): box score lite, shot chart, heatmap, distance covered.

Response shape is D-12 (the plan leaves it unspecified): `box_score`, `shots`, `heatmap`
are exactly what the TV's Review screen renders.

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


def compute(game: dict, events: list[dict], frames: Iterable[dict], profile: dict | None) -> dict:
    players = game.get("players") or []
    x_range, y_range = _court_ranges(profile)
    nx, ny = _heatmap_bins(x_range, y_range)

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
    heatmap = []
    for p in players:
        pid = p["id"]
        mine = [e for e in shots if e.get("player_id") == pid]
        smoothed = _moving_average(paths[pid], SMOOTH_WIN)
        confidences = [float(e.get("confidence") or 0.0) for e in mine]
        rows.append(
            {
                "player_id": pid,
                "name": p.get("name"),
                "team": p.get("team"),
                "attempts": len(mine),
                "makes": sum(1 for e in mine if e.get("made")),
                "confirmed": sum(1 for e in mine if e.get("confirmed")),
                "confidence": (
                    round(sum(confidences) / len(confidences), 2) if confidences else 0.0
                ),
                # R4 distance covered — not on the TV yet, cheap to keep.
                "distance_m": round(
                    sum(math.dist(a, b) for a, b in itertools.pairwise(smoothed)), 1
                ),
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

    return {
        "schema": "replay.stats.v1",
        "game_id": game["id"],
        # R3: stats are always presented as auto-detected; user confirmations count too.
        "auto_detected": True,
        "box_score": rows,
        "shots": [
            {
                "event_id": e["id"],
                "player_id": e.get("player_id"),
                "court": e.get("court"),
                "made": bool(e.get("made")),
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
