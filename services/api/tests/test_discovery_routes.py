"""M11 routes: review queue, extended stats, rally browser, vertical exports, hype."""

from __future__ import annotations

import json
import shutil

import pytest

from .conftest import ready_game


def test_stats_box_score_is_labelled_and_extended(client):
    gid = ready_game(client, client.app_settings)
    body = client.get(f"/games/{gid}/stats").json()
    assert body["label"] == "auto-detected" and 0 < body["confidence"] <= 1
    assert body["available"] == ["shots"]
    rows = {r["player_id"]: r for r in body["box_score"]}
    assert (rows["p1"]["points"], rows["p1"]["misses"], rows["p1"]["unknown"]) == (2, 1, 0)
    assert rows["p1"]["rebounds"] == 0 and rows["p1"]["distance_dropped"] == 0
    assert {s["outcome"] for s in body["shots"]} == {"make", "miss"}


def test_review_queue_maps_to_existing_patches(client):
    gid = ready_game(client, client.app_settings)
    q = client.get(f"/games/{gid}/review/queue").json()["questions"]
    low = next(x for x in q if x["kind"] == "low_confidence")
    assert low["event_id"] == "e_0002"  # confidence 0.55 < 0.6
    no = next(o for o in low["options"] if o["label"] == "No")
    assert client.request(no["method"], no["path"], json=no["body"]).status_code == 200
    q = client.get(f"/games/{gid}/review/queue").json()["questions"]
    assert not any(x.get("event_id") == "e_0002" for x in q)
    stats = client.get(f"/games/{gid}/stats").json()
    assert stats["totals"]["attempts"] == 2  # dismissed: out of the box score


def test_review_queue_asks_only_what_changes_score_or_stats():
    """D-92: no inbound (the 0:00 start) or turnover questions, steals and rebounds by
    name; shots, then rebounds, then steals when the dozen-question cap bites."""
    from replay_api.stats import EVENT_QUESTIONS, review_queue

    def ev(i, t, typ, conf=0.5, **kw):
        return {"id": f"e_{i:04d}", "type": typ, "t_key": t, "confidence": conf, **kw}

    events = [
        ev(0, 0.0, "possession_change", cause="inbound"),
        ev(1, 5.0, "possession_change", cause="steal"),
        ev(2, 5.0, "turnover", 0.4, cause="steal"),
        ev(3, 9.0, "possession_change", cause="defensive_rebound"),
        *(ev(10 + i, 20.0 + i, "shot", made=False) for i in range(EVENT_QUESTIONS - 2)),
        ev(99, 90.0, "shot", 0.9, made=None),
    ]
    q = review_queue({"id": "g", "players": []}, events, [])
    assert len(q) == EVENT_QUESTIONS and q[0]["event_id"] == "e_0099"  # D-93: outcome first
    assert [x["t"] for x in q[1:]] == sorted(x["t"] for x in q[1:])
    prompts = {x["event_id"]: x["prompt"] for x in q}
    assert prompts["e_0003"] == "Was this a defensive rebound?"
    assert prompts["e_0099"] == "Make or miss?"
    assert not {"e_0000", "e_0001", "e_0002"} & set(prompts)  # the steal lost to the cap
    q = review_queue({"id": "g", "players": []}, events[:4], [])
    assert [x["prompt"] for x in q] == ["Was this a steal?", "Was this a defensive rebound?"]


def test_steal_and_rebound_moments_span_the_play():
    """D-92: a possession change is a 0.5 s instant; its moment shows the lead-up."""
    from replay_api.moments import moments

    evs = [{"id": "e_1", "type": "possession_change", "cause": "defensive_rebound",
            "t_key": 30.0, "t_start": 30.0, "t_end": 30.5, "confidence": 0.5},
           {"id": "e_2", "type": "possession_change", "cause": "steal", "t_key": 1.0,
            "t_start": 1.0, "t_end": 1.5, "confidence": 0.5}]  # fmt: skip
    ms = {m["id"]: m for m in moments(evs, {"video": {"duration_s": 31.0}})}
    assert (ms["e_1"]["t_start"], ms["e_1"]["t_end"]) == (26.0, 31.0)
    assert (ms["e_2"]["t_start"], ms["e_2"]["t_end"]) == (0.0, 3.0)


def test_a_pickup_one_point_basket_is_not_a_free_throw():
    from replay_api.moments import label

    shot = {"type": "shot", "made": True, "points": 1}
    assert label(shot, None, "basketball") == "Basket"
    assert label({**shot, "cause": "free_throw"}, None, "basketball") == "Free throw"


def test_a_lost_man_is_a_moment_named_for_the_defender():
    from replay_api.moments import label

    lapse = {"type": "lost_man", "player_id": "p3", "opponent_id": "p1", "max_sep_m": 8.0}
    assert label(lapse, {"name": "Joseph"}, "basketball") == "Lost his man, Joseph"


def test_review_queue_asks_who_untagged_players_are(client):
    gid = ready_game(client, client.app_settings)
    gd = client.app_settings.games_dir / gid
    game = json.loads((gd / "game.json").read_text())
    game["players"][1]["name"] = None  # p2 untagged
    (gd / "game.json").write_text(json.dumps(game))
    q = client.get(f"/games/{gid}/review/queue").json()["questions"]
    who = next(x for x in q if x["kind"] == "identity")
    assert who["player_id"] == "p2" and who["samples"] > 0
    typed = who["options"][0]
    assert typed["text_field"] == "name"
    body = {**typed["body"], typed["text_field"]: "Jordan"}
    assert (
        client.request(typed["method"], typed["path"], json=body).json()["players"][1]["name"]
        == "Jordan"
    )


def test_rally_browser_and_condensed_game(client, tmp_path, monkeypatch):
    pytest.importorskip("replay_render")
    pytest.importorskip("replay_worker")
    if shutil.which("ffmpeg") is None:
        pytest.skip("needs ffmpeg")
    monkeypatch.setenv("REPLAY_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("REPLAY_GPU_LOCK", str(tmp_path / "gpu.lock"))
    gid = ready_game(client, client.app_settings)
    body = client.get(f"/games/{gid}/rallies").json()
    # basketball has no rallies: the condensed game is its shots and turnovers
    assert body["n"] >= 1 and body["condensed"]["status"] == "none"
    assert {r["kind"] for r in body["rallies"]} <= {"shot", "turnover", "block"}
    gd = client.app_settings.games_dir / gid
    doc = json.loads((gd / "events.json").read_text())
    doc["events"].append({"id": "r_1", "type": "rally", "t_start": 2.0, "t_key": 2.0,
                          "t_end": 9.0, "contacts": 6, "confidence": 0.7})  # fmt: skip
    (gd / "events.json").write_text(json.dumps(doc))
    body = client.get(f"/games/{gid}/rallies").json()
    assert body["n"] == 1 and body["rallies"][0]["shots"] == 6 and body["longest"] == ["r1"]
    # what a real pipeline run has and the fake fixture lacks (the stage's inputs)
    (gd / "plays.json").write_text(json.dumps({"plays": []}))
    (gd / "score.json").write_text(json.dumps({"score": []}))
    (gd / "calib.json").write_text("{}")
    r = client.post(f"/games/{gid}/condensed")
    assert r.status_code == 202, r.text
    assert client.app.state.jobs.wait_idle(120)
    got = client.get(f"/games/{gid}/condensed").json()
    assert got["status"] == "done", got
    assert got["condensed_s"] == pytest.approx(9.5, abs=0.1)  # 7 s rally + 1.5 + 1 s
    assert client.get(got["url"]).status_code == 200
    assert client.get(f"/games/{gid}/rallies").json()["rallies"][0]["condensed_t"] == 0.0


def test_vertical_export_renders_once(client, tmp_path, monkeypatch):
    pytest.importorskip("replay_render")
    pytest.importorskip("replay_worker")
    if shutil.which("ffmpeg") is None:
        pytest.skip("needs ffmpeg")
    monkeypatch.setenv("REPLAY_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("REPLAY_GPU_LOCK", str(tmp_path / "gpu.lock"))
    gid = ready_game(client, client.app_settings)
    assert (
        client.post(f"/games/{gid}/exports/vertical", json={"event_id": "nope"}).status_code == 404
    )
    r = client.post(f"/games/{gid}/exports/vertical", json={"event_id": "e_0001"})
    assert r.status_code == 202, r.text
    vid = r.json()["id"]
    assert r.json()["caption"] == "Marcus  ·  MAKE" and r.json()["player_id"] == "p1"
    assert client.app.state.jobs.wait_idle(120)
    got = client.get(f"/games/{gid}/exports/vertical/{vid}").json()
    assert got["status"] == "done", got
    assert got["url"].endswith(f"/media/games/{gid}/exports/vertical/{vid}.mp4")
    assert client.get(got["url"]).status_code == 200
    again = client.post(f"/games/{gid}/exports/vertical", json={"event_id": "e_0001"})
    assert again.status_code == 200 and again.json()["status"] == "done"
    assert [e["id"] for e in client.get(f"/games/{gid}/exports/vertical").json()["exports"]] == [
        vid
    ]
    assert client.get(f"/games/{gid}/exports/vertical/../../x").status_code == 404


def test_highlight_reel_renders_once_per_plan(client, tmp_path, monkeypatch):
    """POST /exports/reel queues one render per plan (aspect + the files the plan reads);
    asking again is the same reel; a new clip makes a new one."""
    pytest.importorskip("replay_render")
    pytest.importorskip("replay_worker")
    if shutil.which("ffmpeg") is None:
        pytest.skip("needs ffmpeg")
    monkeypatch.setenv("REPLAY_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("REPLAY_GPU_LOCK", str(tmp_path / "gpu.lock"))
    gid = ready_game(client, client.app_settings)
    r = client.post(f"/games/{gid}/exports/reel", json={})
    assert r.status_code == 202, r.text
    rid = r.json()["id"]
    assert r.json()["aspect"] == "16:9" and r.json()["job_id"]
    assert client.post(f"/games/{gid}/exports/reel", json={}).json()["id"] == rid  # in flight
    assert client.app.state.jobs.wait_idle(120)
    got = client.get(f"/games/{gid}/exports/reel/{rid}").json()
    assert got["status"] == "done", got
    assert got["url"].endswith(f"/media/games/{gid}/exports/reel/{rid}.mp4")
    assert client.get(got["url"]).status_code == 200
    segs = got["segments"]
    assert segs and got["duration_s"] > 0 and segs[0]["reel_t"] == 0.0
    assert {s["kind"] for s in segs} <= {"top", "clip", "best"}
    assert segs[-1]["kind"] == "best"  # the reel ends on the game's best play
    again = client.post(f"/games/{gid}/exports/reel", json={"aspect": "16:9"})
    assert again.status_code == 200 and again.json()["id"] == rid
    # a bookmark changes the plan: a new reel, with the user's clip in it
    client.post(f"/games/{gid}/events", json={"t": 15.0})
    r2 = client.post(f"/games/{gid}/exports/reel", json={"aspect": "9:16"})
    assert r2.status_code == 202 and r2.json()["id"] != rid
    assert client.app.state.jobs.wait_idle(120)
    got2 = client.get(f"/games/{gid}/exports/reel/{r2.json()['id']}").json()
    assert got2["status"] == "done" and any(s["kind"] == "clip" for s in got2["segments"])
    listed = client.get(f"/games/{gid}/exports/reel").json()["reels"]
    assert [x["id"] for x in listed] == [r2.json()["id"], rid]  # newest first
    assert client.get(f"/games/{gid}/exports/reel/r_..%2F..%2Fx").status_code == 404
    # the user's own best-play pick (edits.json) is a new plan too: the reel ends on it
    pick = {"t": 3.0, "t_start": 1.0, "t_end": 4.0}
    assert client.put(f"/games/{gid}/best-play", json=pick).status_code == 200
    r3 = client.post(f"/games/{gid}/exports/reel", json={"aspect": "9:16"})
    assert r3.status_code == 202 and r3.json()["id"] != r2.json()["id"]


def test_hype_is_computed_on_request(client):
    pytest.importorskip("replay_render")
    gid = ready_game(client, client.app_settings)
    body = client.get(f"/games/{gid}/hype").json()
    assert body["schema"] == "replay.hype.v1" and body["stored"] is False
    assert len(body["values"]) == 40  # 20 s at 2 Hz
