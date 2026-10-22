"""Rule parser cases (plan §4.7). Runs against the fixture game, no HTTP needed."""

from __future__ import annotations

import json

import pytest
from replay_api import pipeline_adapter
from replay_api.providers.query import (
    RuleQueryEngine,
    _merge_overlaps,
    merged_vocab,
)

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


def test_steals_and_rebounds_by_cause():
    evs = EVENTS + [
        {"id": "s1", "type": "possession_change", "cause": "steal", "player_id": "p1",
         "t_start": 10.0, "t_key": 10.2, "t_end": 10.5},
        {"id": "r1", "type": "possession_change", "cause": "defensive_rebound",
         "t_start": 20.0, "t_key": 20.1, "t_end": 20.5},
    ]  # fmt: skip
    eng = RuleQueryEngine()
    steals = eng.query("a steal", GAME, evs)
    assert steals["interpretation"] == "steals"
    assert steals["event_ids"] == ["s1"]
    assert eng.query("Marcus steals", GAME, evs)["interpretation"] == "Marcus — steals"
    assert steals["clips"][0]["label"] == "Marcus steal"
    reb = eng.query("rebounds", GAME, evs)
    assert reb["event_ids"] == ["r1"]
    assert reb["clips"][0]["label"] == "defensive rebound"
    # an unnamed player is "Player N", never the raw track id
    anon = [{**evs[-1], "player_id": "p12"}]
    assert eng.query("rebounds", GAME, anon)["clips"][0]["label"] == "Player 12 defensive rebound"


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


PROFILES = pipeline_adapter.list_sports()


def test_the_profile_catalog_leads_with_the_best_supported_sport():
    """The uploader's sport picker defaults to `/sports[0]`, so the catalog is ordered
    by tier — otherwise adding a Tier 1 sport whose name sorts early (badminton) makes
    it the default for every new game."""
    assert {p["id"] for p in PROFILES} >= {"basketball"}, PROFILES
    tiers = [int(p.get("tier") or 1) for p in PROFILES]
    assert tiers == sorted(tiers, reverse=True), [(p["id"], p.get("tier")) for p in PROFILES]
    assert PROFILES[0]["id"] == "basketball"


@pytest.mark.parametrize("profile", PROFILES, ids=lambda p: p["id"])
def test_every_profile_chip_resolves(profile):
    """S-29/DoD: `sport_ui.chips` is what the TV shows, and every one of them has to hit
    the rule grammar — a chip that returns "No match" is a dead button on the remote.
    Every installed sport, not just basketball: a new profile ships its own chips."""
    chips = (profile.get("sport_ui") or {}).get("chips")
    assert chips, f"{profile['id']}: the profile must ship chips"
    engine = RuleQueryEngine(merged_vocab(profile.get("query_vocab")))
    unresolved = [c for c in chips if engine.query(c, GAME, EVENTS)["interpretation"] == "No match"]
    assert not unresolved, f"{profile['id']}: chips with no interpretation: {unresolved}"


@pytest.mark.parametrize("profile", PROFILES, ids=lambda p: p["id"])
def test_every_profile_vocab_word_resolves(profile):
    """Same rule for `query_vocab`: the words a profile advertises have to parse."""
    engine = RuleQueryEngine(merged_vocab(profile.get("query_vocab")))
    for phrase in profile.get("query_vocab") or {}:
        assert engine.query(phrase, GAME, EVENTS)["interpretation"] != "No match", phrase
