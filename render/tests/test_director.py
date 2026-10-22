"""Director rules on the toy synthetic game (no video needed)."""

from __future__ import annotations

import json
from itertools import pairwise

import pytest
from replay_render.director import Rules, direct, enforce_operator_rules, validate
from replay_render.gamedata import load_game
from replay_render.testing import make_toy_game


@pytest.fixture(scope="module")
def doc(tmp_path_factory):
    gd = make_toy_game(tmp_path_factory.mktemp("g") / "g_toy", video=False)
    return direct(load_game(gd))


def test_cuts_are_contiguous_and_never_overlap(doc):
    validate(doc)
    cuts = doc["cuts"]
    assert cuts[0]["t_start"] == 0.0 and cuts[-1]["t_end"] == doc["duration_s"]
    for a, b in pairwise(cuts):
        assert a["t_end"] == pytest.approx(b["t_start"])
        assert a["t_end"] > a["t_start"]


def test_min_shot_length(doc):
    r = Rules()
    live = [c for c in doc["cuts"] if c["kind"] == "live"]
    # the last cut may be cut short by the end of the game, nothing else may
    for c in live[:-1]:
        assert c["t_end"] - c["t_start"] >= r.min_shot_s - 1e-6, c


def test_replay_inserted_after_a_make_and_trimmed_before_next_action(doc):
    r = Rules()
    replays = [c for c in doc["cuts"] if c["kind"] == "replay"]
    assert [c["replay"]["event_id"] for c in replays] == ["e1"]
    rp = replays[0]
    assert rp["t_start"] == pytest.approx(9.0 + r.replay_delay_s, abs=0.11)
    # next shot at 19 s: its follow-cam starts at 16.5, the replay ends 0.5 s before
    assert rp["t_end"] <= 19.0 - r.shot_pre_s - 0.5 + 1e-6
    assert rp["replay"]["speed"] == 0.5
    src = rp["replay"]["src_t_end"] - rp["replay"]["src_t_start"]
    assert src == pytest.approx((rp["t_end"] - rp["t_start"]) * 0.5, abs=0.06)
    assert rp["replay"]["src_t_end"] == pytest.approx(9.0 + r.replay_post_s)
    assert rp["transition"] == "sting"
    nxt = doc["cuts"][doc["cuts"].index(rp) + 1]
    assert nxt["transition"] == "sting"
    # e2 (19 s) leaves < replay_min_s before the end of the game: no replay
    arc = rp["replay"]["shot_arc"]
    assert arc["to"][2] == 3.05 and arc["t_rim"] == 9.0
    assert doc["geometry"]["projector"] == "homography"


def test_follow_cam_on_the_shooter_and_wide_before_play(doc):
    cams = [(c["camera"], c["t_start"], c["t_end"]) for c in doc["cuts"] if c["kind"] == "live"]
    assert cams[0][0] == "wide"  # players stand still for the first 6 s
    assert any(c == "follow:p1" and s <= 9.0 - 2.5 + 0.11 and e >= 9.0 for c, s, e in cams)


def test_score_and_lower_thirds_from_contract_data(doc):
    g = doc["graphics"]
    assert doc["provisional"] is True  # no score.json: derived from made shots
    assert [s["scores"] for s in g["score"]] == [[2, 0], [2, 3]]
    names = [(l3["name"], l3["line2"]) for l3 in g["lower_thirds"]]
    assert ("Avery", "+2  ·  2 PTS") in names  # tagged name
    assert ("Player 3", "+3  ·  3 PTS") in names  # untagged: tracker number, as on the TV
    l3s = g["lower_thirds"]
    assert all(a["t_end"] <= b["t_start"] for a, b in pairwise(l3s))
    for l3 in g["lower_thirds"]:  # never under a replay
        for c in doc["cuts"]:
            if c["kind"] == "replay":
                assert l3["t_end"] <= c["t_start"] or l3["t_start"] >= c["t_end"]


def test_score_json_wins_over_events(tmp_path):
    gd = make_toy_game(tmp_path / "g", video=False)
    score = {"schema": "replay.score.v1", "score": [
        {"t": 9.0, "scores": [3, 0], "event_id": "e1", "source": "user"}]}  # fmt: skip
    (gd / "score.json").write_text(json.dumps(score))
    d = direct(load_game(gd))
    assert d["provisional"] is False
    assert [s["scores"] for s in d["graphics"]["score"]] == [[3, 0]]


def test_pinhole_camera_recovered_from_the_homography(tmp_path):
    import numpy as np
    from replay_render import testing

    g = load_game(make_toy_game(tmp_path / "g", video=False))
    assert g.projector.model == "homography"
    pts = np.asarray([[0.0, 1.575, 3.05], [3.0, 10.0, 2.0], [-6.0, 20.0, 0.0]])
    assert np.allclose(g.projector.project(pts), testing.project(pts), atol=0.5)


def _seg(t0, t1, cam, kind="live"):
    return {"t_start": t0, "t_end": t1, "camera": cam, "kind": kind, "reason": "", "_ref": None}


def test_no_ping_pong_and_short_shots_absorbed():
    segs = [
        _seg(0, 6, "wide"),
        _seg(6, 8, "tight"),  # A-B-A with a 2 s B
        _seg(8, 14, "wide"),
        _seg(14, 15, "tight"),  # too short, next to a replay
        _seg(15, 20, "tight:p1", "replay"),
        _seg(20, 30, "tight"),
    ]
    out = enforce_operator_rules(segs, Rules())
    assert [(s["camera"], s["t_start"], s["t_end"]) for s in out] == [
        ("wide", 0, 15),
        ("tight:p1", 15, 20),
        ("tight", 20, 30),
    ]
