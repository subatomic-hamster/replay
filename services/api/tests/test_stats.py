"""Stats math on the fixture (box score lite, shot chart, heatmap, distance covered)."""

from __future__ import annotations

import json
import math

from replay_api import stats
from replay_api.pipeline_adapter import BASKETBALL_PROFILE

from .conftest import FAKE_GAME

GAME = json.loads((FAKE_GAME / "game.json").read_text())
EVENTS = json.loads((FAKE_GAME / "events.json").read_text())["events"]


def frames():
    for chunk in sorted((FAKE_GAME / "tracks").glob("*.json")):
        yield from json.loads(chunk.read_text())["frames"]


def result():
    return stats.compute(GAME, EVENTS, frames(), BASKETBALL_PROFILE)


def test_box_score_lite():
    rows = {p["id"]: p for p in result()["players"]}
    assert (rows["p1"]["attempted"], rows["p1"]["made"]) == (2, 1)
    assert (rows["p2"]["attempted"], rows["p2"]["made"]) == (1, 1)
    assert rows["p1"]["name"] == "Marcus"
    assert result()["totals"] == {"attempted": 3, "made": 2}
    assert result()["auto_detected"] is True


def test_shot_chart_points_are_court_metres():
    chart = result()["shot_chart"]
    assert len(chart) == 3
    assert all(p["auto_detected"] for p in chart)
    for point in chart:
        x, y = point["court"]
        assert -7.5 <= x <= 7.5 and 0.0 <= y <= 14.0


def test_heatmap_grid():
    row = result()["players"][0]
    heat = row["heatmap"]
    assert heat["bins"] == [15, 14]
    assert len(heat["grid"]) == 14 and len(heat["grid"][0]) == 15
    # 20 s at 10 Hz, every sample inside the court
    assert sum(sum(r) for r in heat["grid"]) == 200 == row["samples"]


def test_distance_covered_matches_the_fixture_path():
    rows = {p["id"]: p for p in result()["players"]}
    # p1 traces 3*sin(0.30t), 6+3*cos(0.25t): speed ~0.75-0.9 m/s over 20 s
    expected = sum(
        math.dist(
            (3 * math.sin(0.30 * t / 10), 6 + 3 * math.cos(0.25 * t / 10)),
            (3 * math.sin(0.30 * (t + 1) / 10), 6 + 3 * math.cos(0.25 * (t + 1) / 10)),
        )
        for t in range(199)
    )
    assert (
        rows["p1"]["distance_m"] == round(expected, 1)
        or abs(rows["p1"]["distance_m"] - expected) < 1.0
    )  # smoothing shortens the path slightly
    assert 5.0 < rows["p2"]["distance_m"] < 40.0


def test_empty_game_does_not_explode():
    out = stats.compute({"id": "g_x", "players": [], "video": {}}, [], iter([]), BASKETBALL_PROFILE)
    assert out["players"] == [] and out["totals"] == {"attempted": 0, "made": 0}
