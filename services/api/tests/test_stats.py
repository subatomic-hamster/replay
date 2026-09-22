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
    rows = {p["player_id"]: p for p in result()["box_score"]}
    assert (rows["p1"]["attempts"], rows["p1"]["makes"]) == (2, 1)
    assert (rows["p2"]["attempts"], rows["p2"]["makes"]) == (1, 1)
    assert rows["p1"]["name"] == "Marcus"
    assert result()["totals"] == {"attempts": 3, "makes": 2}
    assert result()["auto_detected"] is True


def test_shot_chart_points_are_court_metres():
    chart = result()["shots"]
    assert len(chart) == 3
    assert {"event_id", "player_id", "court", "made", "confirmed"} <= set(chart[0])
    for point in chart:
        x, y = point["court"]
        assert -7.5 <= x <= 7.5 and 0.0 <= y <= 14.0


def test_heatmap_grid():
    out = result()
    heat = out["heatmap"][0]
    assert (heat["cols"], heat["rows"]) == (15, 14)
    assert len(heat["values"]) == 15 * 14
    # 20 s at 10 Hz, every sample inside the court
    samples = next(r["samples"] for r in out["box_score"] if r["player_id"] == heat["player_id"])
    assert sum(heat["values"]) == 200 == samples


def test_distance_covered_matches_the_fixture_path():
    rows = {p["player_id"]: p for p in result()["box_score"]}
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
    assert out["box_score"] == [] and out["totals"] == {"attempts": 0, "makes": 0}
