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
    assert body["n"] == 0 and body["condensed"]["status"] == "none"
    assert client.post(f"/games/{gid}/condensed").status_code == 409
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


def test_hype_is_computed_on_request(client):
    pytest.importorskip("replay_render")
    gid = ready_game(client, client.app_settings)
    body = client.get(f"/games/{gid}/hype").json()
    assert body["schema"] == "replay.hype.v1" and body["stored"] is False
    assert len(body["values"]) == 40  # 20 s at 2 Hz
