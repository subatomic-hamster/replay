"""Rule parser cases (plan §4.7). Runs against the fixture game, no HTTP needed."""

from __future__ import annotations

import json

import pytest
from replay_api.providers.query import RuleQueryEngine, _merge_overlaps

from .conftest import FAKE_GAME

GAME = json.loads((FAKE_GAME / "game.json").read_text())
EVENTS = json.loads((FAKE_GAME / "events.json").read_text())["events"]


def run(text: str) -> dict:
    return RuleQueryEngine().query(text, GAME, EVENTS)


def test_player_and_all_shots():
    out = run("Marcus — all shots")
    assert out["interpretation"] == "Marcus — all shots"
    assert [c["event_id"] for c in out["clips"]] == ["e_0001", "e_0002"]
    assert out["clips"][0]["t_start"] == 0.5  # 2.0 - 1.5 pad
    assert out["clips"][0]["t_end"] == 8.5  # 7.0 + 1.5 pad
    assert out["clips"][0]["label"] == "Marcus made"


def test_fuzzy_player_name():
    assert run("marcuss shots")["interpretation"].startswith("Marcus")
    assert run("alex makes")["interpretation"] == "Alex — made shots"


def test_makes():
    out = run("makes")
    assert out["interpretation"] == "made shots"
    assert {c["event_id"] for c in out["clips"]} == {"e_0001", "e_0003"}


def test_misses_second_half():
    out = run("misses second half")
    assert out["interpretation"] == "missed shots — 2nd half"
    assert [c["event_id"] for c in out["clips"]] == ["e_0002"]
    assert run("misses first half")["clips"] == []


def test_bookmarks():
    out = run("bookmarks")
    assert out["interpretation"] == "bookmarks"
    assert [c["event_id"] for c in out["clips"]] == ["e_0004"]


def test_top_plays_sorted_by_confidence():
    out = run("top plays")
    assert out["interpretation"] == "top plays"
    assert [c["event_id"] for c in out["clips"]] == ["e_0001", "e_0003"]


def test_last_n_minutes():
    out = run("all shots last 1 minute")  # fixture is 20 s, so everything is inside
    assert out["interpretation"] == "all shots — last 1 min"
    # 3 events, but the last two overlap after padding and merge into one clip
    assert len(out["clips"]) == 2


def test_player_alone_means_their_shots():
    assert run("Alex")["interpretation"] == "Alex — all shots"


@pytest.mark.parametrize("text", ["how many pizzas", "", "   ", "zzzz"])
def test_unknown_text(text):
    assert run(text) == {"interpretation": "No match", "clips": []}


def test_clips_never_run_past_the_video():
    for clip in run("all shots")["clips"]:
        assert 0.0 <= clip["t_start"] < clip["t_end"] <= GAME["video"]["duration_s"]


def test_overlapping_clips_merge():
    merged = _merge_overlaps(
        [
            {"t_start": 0.0, "t_end": 5.0, "event_id": "a", "label": "a"},
            {"t_start": 4.0, "t_end": 9.0, "event_id": "b", "label": "b"},
            {"t_start": 20.0, "t_end": 22.0, "event_id": "c", "label": "c"},
        ]
    )
    assert [(c["t_start"], c["t_end"], c["event_id"]) for c in merged] == [
        (0.0, 9.0, "a"),
        (20.0, 22.0, "c"),
    ]
