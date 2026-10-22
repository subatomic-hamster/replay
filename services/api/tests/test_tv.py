"""TV redesign backend (docs/ux/redesign.md "What the backend needs"), local mode: hero art,
storyboard, moments, `watchable`, `eta_s`, `stage_label`, `features`, and their auth."""

from __future__ import annotations

import dataclasses

from fastapi.testclient import TestClient
from replay_api import readiness
from replay_api.main import create_app

from .conftest import CALIB, TINY_MP4, new_game
from .test_flow import poll_until_ready


def _processed(client: TestClient) -> str:
    gid = new_game(client, "TV run")
    assert client.put(f"/games/{gid}/upload", content=TINY_MP4.read_bytes()).status_code == 200
    # the upload's length is known before processing, so a run has an ETA from the start
    assert 19.5 < client.get(f"/games/{gid}").json()["video"]["duration_s"] < 20.5
    assert client.post(f"/games/{gid}/calibration", json=CALIB).status_code == 200
    assert client.post(f"/games/{gid}/process").status_code == 202
    assert poll_until_ready(client, gid)["status"] == "ready"
    return gid


def test_processed_game_has_hero_storyboard_moments_and_features(client: TestClient):
    gid = _processed(client)
    game = client.get(f"/games/{gid}").json()
    assert game["watchable"] is True and "eta_s" not in game and "stage_label" not in game
    assert game["hero_url"].endswith(f"/media/games/{gid}/media/hero.jpg")
    assert client.get(game["hero_url"]).content[:2] == b"\xff\xd8"
    f = {k: v["state"] for k, v in game["features"].items()}
    assert f == {"moments": "ready", "previews": "ready", "follow": "ready",
                 "angles": "unavailable", "free_view": "unavailable", "pov": "unavailable",
                 "highlights": "unavailable", "condensed": "unavailable",
                 "stats": "ready", "commentary": "ready"}  # fmt: skip

    sb = client.get(game["storyboard_url"]).json()
    assert (sb["interval_s"], sb["width"], sb["height"], sb["cols"], sb["rows"]) == (
        2,
        320,
        180,
        10,
        10,
    )
    assert sb["count"] == 10 and len(sb["sheets"]) == 1  # 20 s at one frame per 2 s
    assert client.get(sb["sheets"][0]).content[:2] == b"\xff\xd8"

    ms = client.get(f"/games/{gid}/moments").json()
    assert [m["t"] for m in ms] == sorted(m["t"] for m in ms)
    shots = [(m["id"], m["kind"], m["label"]) for m in ms if m["kind"] != "bookmark"]
    # fixture events: made/missed shots with no shot value; labels say only that
    assert shots == [("e_0001", "score", "Basket, Marcus"), ("e_0002", "play", "Missed shot, Marcus"),
                     ("e_0003", "score", "Basket, Alex")]  # fmt: skip
    assert ms[0]["player"] == {"id": "p1", "name": "Marcus", "color_hex": "#1F4FA0"}
    assert all(client.get(m["thumb_url"]).status_code == 200 for m in ms)

    # the summary row carries the same readiness
    row = next(g for g in client.get("/games").json() if g["id"] == gid)
    assert row["watchable"] and row["hero_url"] == game["hero_url"]
    assert row["features"] == game["features"]


def test_moments_follow_edits_and_bookmarks_get_a_frame(client: TestClient):
    gid = _processed(client)
    assert client.patch(f"/games/{gid}/events/e_0002", json={"dismissed": True}).status_code == 200
    assert client.patch(f"/games/{gid}/players/p1", json={"name": "Maya"}).status_code == 200
    bm = client.post(f"/games/{gid}/events", json={"t": 12.0}).json()
    ms = {m["id"]: m for m in client.get(f"/games/{gid}/moments").json()}
    assert "e_0002" not in ms  # dismissed: not a moment
    assert ms["e_0001"]["label"] == "Basket, Maya"  # renamed at once, no re-run
    assert ms[bm["id"]]["kind"] == "bookmark" and ms[bm["id"]]["label"] == "Your bookmark"
    assert client.get(ms[bm["id"]]["thumb_url"]).content[:2] == b"\xff\xd8"


def test_moments_need_the_key_not_the_upload_token(settings):
    keyed = dataclasses.replace(settings, api_key="s3cret", upload_token_secret="sec")
    with TestClient(create_app(keyed)) as c:
        g = c.post("/games", json={"title": "x"}, headers={"X-Replay-Key": "s3cret"}).json()
        tok = {"X-Replay-Upload-Token": g["upload_token"]}
        assert c.get(f"/games/{g['id']}", headers=tok).status_code == 200  # the phone's
        assert c.get(f"/games/{g['id']}/moments", headers=tok).status_code == 401
        assert c.get(f"/games/{g['id']}/storyboard", headers=tok).status_code == 401
        assert c.get(f"/games/{g['id']}/moments", headers={"X-Replay-Key": "s3cret"}).json() == []
        assert c.get(f"/games/{g['id']}/storyboard",
                     headers={"X-Replay-Key": "s3cret"}).status_code == 404  # fmt: skip


def _mid_run(**kw) -> dict:
    stages = dict.fromkeys(("ingest", "calibrate", "detect", "track", "events"), "pending")
    stages.update(ingest="done", calibrate="done", detect="running")
    return {"status": "processing", "stages": stages, "progress": {"detect": 0.5},
            "video": {"duration_s": 600.0}, **kw}  # fmt: skip


def test_readiness_mid_run():
    files = {"media/wide.mp4", "storyboard/manifest.json"}
    has = lambda pat: pat in files
    out = readiness.fields(_mid_run(), has)
    assert out["watchable"] is True and out["stage_label"] == "Finding players"
    cost = lambda s: readiness._cost(s, 600.0)
    left = cost("detect") * 0.5 + cost("track") + cost("events")
    assert out["eta_s"] == -(-(left + cost("_finish")) // 1)  # ceil, seconds
    f = out["features"]
    assert f["previews"] == {"state": "ready"}
    assert f["moments"] == {"state": "pending", "eta_s": out["eta_s"]}
    assert f["stats"]["state"] == "pending" and f["stats"]["eta_s"] < out["eta_s"]
    assert f["angles"] == {"state": "unavailable"}  # opt-in stages not configured
    # configured opt-in stages are pending, with no made-up ETA
    assert readiness.fields(_mid_run(), has, ("replays",))["features"]["angles"] == {
        "state": "pending"
    }
    # mid-ingest the mezzanine is still being written: not watchable yet
    early = _mid_run()
    early["stages"].update(ingest="running", calibrate="pending", detect="pending")
    assert readiness.fields(early, has)["watchable"] is False
    # no duration known: no ETA rather than a wrong one
    assert "eta_s" not in readiness.fields(_mid_run(video={}), has)
    # cloud: one runner poll while queued
    queued = readiness.fields({**_mid_run(), "status": "queued"}, has, cloud=True)
    assert queued["stage_label"] == "Waiting to start" and queued["eta_s"] > out["eta_s"] + 25
