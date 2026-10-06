"""D-61: user corrections survive re-processing (they live in edits.json and are
re-applied to the pipeline's files), and the smaller fixes of the same wave."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient
from replay_api import edits

from .conftest import CALIB, TINY_MP4, new_game
from .test_flow import poll_until_ready
from .test_plays_routes import _seed


def _processed(client: TestClient) -> str:
    gid = new_game(client, "Edits survive")
    assert client.put(f"/games/{gid}/upload", content=TINY_MP4.read_bytes()).status_code == 200
    assert client.post(f"/games/{gid}/calibration", json=CALIB).status_code == 200
    _reprocess(client, gid)
    return gid


def _reprocess(client: TestClient, gid: str) -> dict:
    assert client.post(f"/games/{gid}/process").status_code == 202
    game = poll_until_ready(client, gid)
    assert game["status"] == "ready", game
    return game


def _event(client: TestClient, gid: str, eid: str) -> dict | None:
    evs = client.get(f"/media/games/{gid}/events.json").json()["events"]
    return next((e for e in evs if e["id"] == eid), None)


def test_event_roster_and_score_corrections_survive_reprocessing(client: TestClient):
    gid = _processed(client)
    assert client.patch(f"/games/{gid}/events/e_0002", json={"made": True}).status_code == 200
    assert client.patch(f"/games/{gid}/events/e_0003", json={"dismissed": True}).status_code == 200
    assert client.patch(f"/games/{gid}/events/e_0001", json={"confirmed": True}).status_code == 200
    mark = client.post(f"/games/{gid}/events", json={"t": 4.0}).json()
    assert client.patch(f"/games/{gid}/players/p1", json={"name": "Big Marcus"}).status_code == 200
    assert client.post(f"/games/{gid}/score", json={"t": 1.0, "scores": [4, 4]}).status_code == 201

    game = _reprocess(client, gid)  # the fake pipeline rewrites every file it owns

    assert next(p for p in game["players"] if p["id"] == "p1")["name"] == "Big Marcus"
    assert _event(client, gid, "e_0002")["made"] is True
    assert _event(client, gid, "e_0002")["source"] == "user"
    assert _event(client, gid, "e_0003")["dismissed"] is True
    e1 = _event(client, gid, "e_0001")
    assert e1["confirmed"] is True and e1["source"] == "heuristic"  # "Yes" keeps the source
    assert _event(client, gid, mark["id"])["type"] == "bookmark"
    score = client.get(f"/games/{gid}/score").json()["score"]
    assert [s["scores"] for s in score if s["source"] == "user"] == [[4, 4]]
    stats = client.get(f"/games/{gid}/stats").json()
    p1 = next(r for r in stats["box_score"] if r["player_id"] == "p1")
    assert p1["name"] == "Big Marcus" and p1["makes"] == 2


def test_merge_survives_reprocessing(client: TestClient):
    gid = _processed(client)
    assert client.patch(f"/games/{gid}/players/p2", json={"merge_into": "p1"}).status_code == 200
    game = _reprocess(client, gid)
    assert [p["id"] for p in game["players"]] == ["p1"]
    chunk = client.get(f"/media/games/{gid}/tracks/00000.json").json()
    assert {e["id"] for f in chunk["frames"] for e in f["p"]} == {"p1"}
    assert client.get(f"/media/games/{gid}/crops/p2.json").status_code == 404
    assert _event(client, gid, "e_0003")["player_id"] == "p1"


def test_tap_and_trim_survive_a_restore_and_trim_sets_edited(client: TestClient):
    gid = _seed(client)
    gd = client.app_settings.games_dir / gid
    pristine = {
        rel: (gd / rel).read_text() for rel in ("plays.json", "triggers.json", "clips.json")
    }
    assert client.get(f"/games/{gid}/clips").json()["clips"][0]["edited"] is False  # absent
    tap = client.post(f"/games/{gid}/triggers", json={"t": 17.0}).json()
    trim = client.patch(f"/games/{gid}/clips/c_0001", json={"t_start": 2.0, "t_end": 6.5}).json()
    assert trim["edited"] is True and trim["source"] == "user"

    for rel, text in pristine.items():  # what a worker cache restore does
        (gd / rel).write_text(text)
    edits.apply(gd)

    clips = {c["id"]: c for c in client.get(f"/games/{gid}/clips").json()["clips"]}
    assert (clips["c_0001"]["t_start"], clips["c_0001"]["edited"]) == (2.0, True)
    assert clips[tap["clip"]["id"]]["edited"] is False
    assert tap["trigger"]["id"] in [t["id"] for t in client.get(f"/games/{gid}/triggers").json()["triggers"]]  # fmt: skip
    plays = client.get(f"/games/{gid}/plays").json()["plays"]
    assert plays[1]["trigger"]["id"] == tap["trigger"]["id"]
    edits.apply(gd)  # idempotent
    assert len(client.get(f"/games/{gid}/clips").json()["clips"]) == 2


def test_games_list_tolerates_null_recorded_at(client: TestClient, settings):
    gid = new_game(client, "Worker-made")
    p = settings.games_dir / gid / "game.json"
    p.write_text(json.dumps({**json.loads(p.read_text()), "recorded_at": None}))
    new_game(client, "Normal")
    r = client.get("/games")
    assert r.status_code == 200
    assert [g["title"] for g in r.json()][-1] == "Worker-made"  # undated sorts last


def test_deleted_export_with_a_done_job_reads_missing(client: TestClient, settings):
    gid = _seed(client)
    gd = settings.games_dir / gid
    jobs = client.app.state.jobs
    vid = "v_0123456789ab"
    (gd / "exports/vertical").mkdir(parents=True)
    (gd / f"exports/vertical/{vid}.json").write_text(json.dumps({"id": vid, "t_start": 0}))
    job = jobs.submit(f"vertical:{vid}", gid, lambda job_id: None)
    assert jobs.wait_idle(10) and jobs.get(job["id"])["status"] == "done"
    out = client.get(f"/games/{gid}/exports/vertical/{vid}").json()
    assert out["status"] == "missing" and out["url"] is None

    job = jobs.submit("condensed", gid, lambda job_id: None)
    assert jobs.wait_idle(10)
    assert client.get(f"/games/{gid}/condensed").json()["status"] == "missing"


def test_confirmed_events_count_as_verified_in_stats(client: TestClient):
    gid = _seed(client)
    before = client.get(f"/games/{gid}/stats").json()
    assert client.patch(f"/games/{gid}/events/e_0002", json={"confirmed": True}).status_code == 200
    after = client.get(f"/games/{gid}/stats").json()
    assert after["confirmed"] == before["confirmed"] + 1
    assert after["confidence"] > before["confidence"]  # a verified event counts as 1.0
    row = next(r for r in after["box_score"] if r["player_id"] == "p1")
    assert row["confirmed"] == 1
