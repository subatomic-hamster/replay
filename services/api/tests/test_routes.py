"""Every route in plan §4.6: status codes, required fields, error cases."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from .conftest import CALIB, TINY_MP4, new_game, ready_game


def test_healthz(client: TestClient):
    body = client.get("/healthz").json()
    assert body["ok"] is True
    assert body["providers"]["pipeline"] == "fake"


def test_sports(client: TestClient):
    r = client.get("/sports")
    assert r.status_code == 200
    sport = r.json()["sports"][0]
    assert sport["id"] == "basketball"
    assert {"display_name", "tier", "court", "sport_ui"} <= set(sport)
    assert "corner_nl" in sport["court"]["landmarks"]
    assert sport["court"]["variants"] == ["half", "full"]
    assert sport["sport_ui"]["chips"]


def test_create_game_and_upload_url(client: TestClient):
    r = client.post("/games", json={"title": "Tuesday run", "sport": "basketball"})
    assert r.status_code == 201
    body = r.json()
    assert body["id"].startswith("g_")
    assert body["upload_url"].endswith(f"/games/{body['id']}/upload")


def test_create_game_rejects_unknown_sport_and_empty_title(client: TestClient):
    assert client.post("/games", json={"title": "x", "sport": "quidditch"}).status_code == 400
    assert client.post("/games", json={"title": ""}).status_code == 422


def test_unknown_game_is_404(client: TestClient):
    for method, path in [
        ("get", "/games/g_missing"),
        ("post", "/games/g_missing/process"),
        ("get", "/games/g_missing/stats"),
    ]:
        r = getattr(client, method)(path)
        assert r.status_code == 404, path
        assert "detail" in r.json()


def test_upload_put_and_post(client: TestClient):
    gid = new_game(client)
    data = TINY_MP4.read_bytes()
    r = client.put(f"/games/{gid}/upload", content=data)
    assert r.status_code == 200
    assert r.json()["size"] == len(data)
    assert client.get(f"/games/{gid}").json()["status"] == "uploaded"

    gid2 = new_game(client, "multipart")
    r = client.post(f"/games/{gid2}/upload", files={"file": ("tiny.mp4", data, "video/mp4")})
    assert r.status_code == 200 and r.json()["size"] == len(data)


def test_empty_upload_is_400(client: TestClient):
    gid = new_game(client)
    assert client.put(f"/games/{gid}/upload", content=b"").status_code == 400


def test_calibration_rejects_landmarks_that_do_not_form_a_court(client: TestClient):
    gid = new_game(client)
    # collinear clicks: no homography at all
    degenerate = {
        **CALIB,
        "landmarks_px": {k: [10.0 * i, 10.0 * i] for i, k in enumerate(CALIB["landmarks_px"], 1)},
    }
    r = client.post(f"/games/{gid}/calibration", json=degenerate)
    assert r.status_code == 400 and r.json()["detail"]

    # plausible corners but a rim clicked 300 px off: reprojection error too high
    off = {**CALIB, "landmarks_px": {**CALIB["landmarks_px"], "rim": [340.0, 583.2]}}
    r = client.post(f"/games/{gid}/calibration", json=off)
    assert r.status_code == 400 and "reprojection" in r.json()["detail"].lower()
    assert client.get(f"/games/{gid}").json().get("court") is None  # nothing stored


def test_calibration_validation(client: TestClient):
    gid = new_game(client)
    bad = {**CALIB, "landmarks_px": {k: v for k, v in list(CALIB["landmarks_px"].items())[:3]}}
    assert client.post(f"/games/{gid}/calibration", json=bad).status_code == 400

    no_rim = {
        **CALIB,
        "landmarks_px": {k: v for k, v in CALIB["landmarks_px"].items() if k != "rim"},
    }
    r = client.post(f"/games/{gid}/calibration", json=no_rim)
    assert r.status_code == 400 and "rim" in r.json()["detail"]

    assert (
        client.post(f"/games/{gid}/calibration", json={**CALIB, "variant": "octagon"}).status_code
        == 400
    )
    assert (
        client.post(f"/games/{gid}/calibration", json={**CALIB, "sport": "quidditch"}).status_code
        == 400
    )
    assert client.post(f"/games/{gid}/calibration", json={"sport": "basketball"}).status_code == 422


def test_calibration_stores_court(client: TestClient):
    gid = new_game(client)
    r = client.post(f"/games/{gid}/calibration", json=CALIB)
    assert r.status_code == 200
    assert r.json()["court"]["variant"] == "half"
    err = r.json()["reprojection_error_px"]  # None if courtcam is not installed
    assert err is None or err < 5.0
    court = client.get(f"/games/{gid}").json()["court"]
    assert court["landmarks_px"]["rim"] == [641.1, 583.2]


def test_process_requires_upload_and_calibration(client: TestClient):
    gid = new_game(client)
    r = client.post(f"/games/{gid}/process")
    assert r.status_code == 400 and "uploaded" in r.json()["detail"]
    client.put(f"/games/{gid}/upload", content=TINY_MP4.read_bytes())
    r = client.post(f"/games/{gid}/process")
    assert r.status_code == 400 and "calibrated" in r.json()["detail"]


def test_library_list(client: TestClient, settings):
    gid = ready_game(client, settings, "Fixture game")
    games = client.get("/games").json()["games"]
    row = next(g for g in games if g["id"] == gid)
    assert set(row) == {
        "id",
        "title",
        "status",
        "stages",
        "duration_s",
        "thumbnail",
        "recorded_at",
        "sport",
    }
    assert row["duration_s"] == 20.0
    assert row["thumbnail"].endswith(f"/media/games/{gid}/media/thumb.jpg")


def test_get_game_resolves_urls(client: TestClient, settings):
    gid = ready_game(client, settings)
    g = client.get(f"/games/{gid}").json()
    prefix = f"http://testserver/media/games/{gid}/"
    assert g["renditions"]["wide"] == prefix + "media/wide.mp4"
    assert g["tracks"]["url_template"] == prefix + "tracks/{chunk:05d}.json"
    assert g["croppaths"]["url_template"] == prefix + "crops/{player_id}.json"
    assert g["events_url"] == prefix + "events.json"
    assert g["schema"] == "replay.game.v1"
    assert [p["name"] for p in g["players"]] == ["Marcus", "Alex"]


def test_patch_player_rename(client: TestClient, settings):
    gid = ready_game(client, settings)
    r = client.patch(f"/games/{gid}/players/p1", json={"name": "Big Marcus"})
    assert r.status_code == 200
    p1 = next(p for p in r.json()["players"] if p["id"] == "p1")
    assert p1["name"] == "Big Marcus" and p1["tagged"] is True
    assert client.patch(f"/games/{gid}/players/p9", json={"name": "Nope"}).status_code == 404
    assert client.patch(f"/games/{gid}/players/p1", json={}).status_code == 400


def test_patch_player_merge_rewrites_ids(client: TestClient, settings):
    gid = ready_game(client, settings)
    r = client.patch(f"/games/{gid}/players/p2", json={"merge_into": "p1"})
    assert r.status_code == 200
    assert [p["id"] for p in r.json()["players"]] == ["p1"]

    body = client.get(f"/media/games/{gid}/events.json").json()
    assert all(e["player_id"] in (None, "p1") for e in body["events"])
    chunk = client.get(f"/media/games/{gid}/tracks/00000.json").json()
    assert {e["id"] for f in chunk["frames"] for e in f["p"]} == {"p1"}
    assert len(chunk["frames"][0]["p"]) == 1  # deduped inside the frame
    assert client.get(f"/media/games/{gid}/crops/p2.json").status_code == 404

    assert client.patch(f"/games/{gid}/players/p1", json={"merge_into": "p1"}).status_code == 400
    assert client.patch(f"/games/{gid}/players/p1", json={"merge_into": "p9"}).status_code == 404


def test_render_player(client: TestClient, settings):
    gid = ready_game(client, settings)
    r = client.post(f"/games/{gid}/players/p1/render")
    assert r.status_code == 202 and r.json()["status"] in ("queued", "running", "done")
    assert client.post(f"/games/{gid}/players/p9/render").status_code == 404
    assert client.app.state.jobs.wait_idle(10)
    job = client.app.state.jobs.get(r.json()["job_id"])
    assert job["status"] == "done"  # fake mode: done without a file


def test_patch_event(client: TestClient, settings):
    gid = ready_game(client, settings)
    r = client.patch(f"/games/{gid}/events/e_0001", json={"confirmed": True})
    assert r.status_code == 200
    assert r.json()["confirmed"] is True and r.json()["source"] == "heuristic"

    r = client.patch(f"/games/{gid}/events/e_0002", json={"made": True})
    assert r.json()["made"] is True
    assert r.json()["source"] == "user" and r.json()["confirmed"] is True

    assert client.patch(f"/games/{gid}/events/e_9999", json={"made": True}).status_code == 404
    assert client.patch(f"/games/{gid}/events/e_0001", json={"hax": 1}).status_code == 400


def test_create_bookmark(client: TestClient, settings):
    gid = ready_game(client, settings)
    r = client.post(f"/games/{gid}/events", json={"t": 12.0})
    assert r.status_code == 201
    ev = r.json()
    assert (ev["type"], ev["t_start"], ev["t_key"], ev["t_end"]) == ("bookmark", 9.0, 12.0, 14.0)
    assert ev["source"] == "user"
    assert client.post(f"/games/{gid}/events", json={"t": -1}).status_code == 422
    assert len(client.get(f"/media/games/{gid}/events.json").json()["events"]) == 5


def test_bookmark_clamps_to_video_bounds(client: TestClient, settings):
    gid = ready_game(client, settings)
    ev = client.post(f"/games/{gid}/events", json={"t": 1.0}).json()
    assert ev["t_start"] == 0.0
    ev = client.post(f"/games/{gid}/events", json={"t": 19.5}).json()
    assert ev["t_end"] == 20.0


def test_query_route(client: TestClient, settings):
    gid = ready_game(client, settings)
    r = client.post(f"/games/{gid}/query", json={"text": "Marcus — all shots"})
    assert r.status_code == 200
    body = r.json()
    assert body["interpretation"] == "Marcus — all shots"
    assert len(body["clips"]) == 2
    assert set(body["clips"][0]) == {"t_start", "t_end", "event_id", "label"}
    assert client.post(f"/games/{gid}/query", json={"text": ""}).status_code == 422


def test_stats_route(client: TestClient, settings):
    gid = ready_game(client, settings)
    body = client.get(f"/games/{gid}/stats").json()
    assert body["schema"] == "replay.stats.v1" and body["auto_detected"] is True
    assert body["totals"] == {"attempted": 3, "made": 2}


def test_sessions_and_ws_fanout(client: TestClient):
    r = client.post("/sessions")
    assert r.status_code == 201
    sid, code = r.json()["sid"], r.json()["code"]
    assert len(code) == 4 and code.isdigit()
    with (
        client.websocket_connect(f"/sessions/{sid}") as tv,
        client.websocket_connect(f"/sessions/{sid}") as phone,
    ):
        phone.send_json({"type": "query", "text": "makes"})
        assert tv.receive_json() == {"type": "query", "text": "makes"}


def test_ws_unknown_session_is_closed(client: TestClient):
    with pytest.raises(WebSocketDisconnect), client.websocket_connect("/sessions/s_nope") as ws:
        ws.receive_text()
