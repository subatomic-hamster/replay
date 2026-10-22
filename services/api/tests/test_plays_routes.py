"""M4/M5 routes: plays, tap triggers, clips (trim, voice subject), score corrections."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from .conftest import ready_game


def _seed(client: TestClient) -> str:
    """The fixture game plus pipeline-shaped plays / triggers / clips files."""
    s = client.app_settings
    gid = ready_game(client, s)
    d = s.games_dir / gid
    plays = [
        {"id": "pl_0001", "sport": "basketball", "grammar": "possession", "t_start": 1.0,
         "t_end": 7.0, "participants": [{"player_id": "p1", "role": "shooter"}], "team": 0},
        {"id": "pl_0002", "sport": "basketball", "grammar": "possession", "t_start": 8.0,
         "t_end": 15.5, "participants": [{"player_id": "p2", "role": "inbounder"}], "team": 1},
    ]  # fmt: skip
    voice = {"id": "tr_0001", "type": "voice", "t": 9.0, "transcript": "Replay, clip Alex.",
             "play_id": "pl_0001", "clip_id": "c_0001", "source": "auto"}  # fmt: skip
    clip = {"id": "c_0001", "play_id": "pl_0001", "trigger_id": "tr_0001", "t_start": 0.0,
            "t_end": 8.0, "attribution": {"owner_player_id": None, "by_player_id": None,
            "subject_player_id": None}, "participants": ["p1"], "source": "auto"}  # fmt: skip
    for rel, schema, key, items in (
        ("plays.json", "replay.plays.v1", "plays", plays),
        ("triggers.json", "replay.triggers.v1", "triggers", [voice]),
        ("clips.json", "replay.clips.v1", "clips", [clip]),
    ):
        (d / rel).write_text(json.dumps({"schema": schema, key: items}))
    return gid


def test_plays_and_empty_game(client: TestClient):
    gid = _seed(client)
    r = client.get(f"/games/{gid}/plays")
    assert r.status_code == 200 and [p["id"] for p in r.json()["plays"]] == ["pl_0001", "pl_0002"]
    assert client.get(f"/games/{gid}/plays?grammar=rally").json()["plays"] == []
    bare = ready_game(client, client.app_settings, "No plays yet")
    assert client.get(f"/games/{bare}/plays").json()["plays"] == []
    assert client.get(f"/games/{bare}/clips").json()["clips"] == []
    assert client.get("/games/nope/plays").status_code == 404


def test_tap_resolves_to_the_play_that_just_ended(client: TestClient):
    gid = _seed(client)
    r = client.post(f"/games/{gid}/triggers", json={"t": 17.0, "by_player_id": "p2"})
    assert r.status_code == 201, r.text
    trig, clip = r.json()["trigger"], r.json()["clip"]
    assert trig["play_id"] == "pl_0002" and trig["source"] == "user" and trig["type"] == "tap"
    assert clip["play_id"] == "pl_0002" and clip["t_start"] == 7.0
    assert clip["t_end"] == 16.5 and clip["attribution"]["owner_player_id"] == "p2"
    assert clip["source"] == "user" and clip["participants"] == ["p2"]

    plays = client.get(f"/games/{gid}/plays").json()["plays"]
    assert plays[1]["trigger"]["id"] == trig["id"]
    triggers = client.get(f"/games/{gid}/triggers").json()["triggers"]
    assert [(t["id"], t["play_id"], t["clip_id"]) for t in triggers] == [
        ("tr_0001", "pl_0001", "c_0001"),  # filled in from clips.json
        (trig["id"], "pl_0002", clip["id"]),
    ]
    assert clip["id"] in [c["id"] for c in client.get(f"/games/{gid}/clips").json()["clips"]]

    # too long after any play: stored, but no clip
    r = client.post(f"/games/{gid}/triggers", json={"t": 19.9})
    assert r.status_code == 201 and r.json()["clip"] is not None  # 15.5 + 8 covers it
    assert client.post(f"/games/{gid}/triggers", json={"t": 0.5}).json()["clip"] is None
    assert client.post(f"/games/{gid}/triggers", json={"t": 99}).status_code == 400
    r = client.post(f"/games/{gid}/triggers", json={"t": 5, "by_player_id": "p9"})
    assert r.status_code == 404


def test_user_clips_are_bookmark_moments(client: TestClient):
    """ "Replay, clip that", the X sign and phone taps reach the TV's Moments row as the
    user's own (`bookmark`) moments, over the clip's range."""
    gid = _seed(client)
    d = client.app_settings.games_dir / gid
    doc = json.loads((d / "triggers.json").read_text())
    doc["triggers"].append({"id": "tr_0002", "type": "gesture", "t": 17.0, "t_start": 16.0,
                            "by_player_id": "p1", "confidence": 0.8, "source": "auto"})  # fmt: skip
    (d / "triggers.json").write_text(json.dumps(doc))
    tap = client.post(f"/games/{gid}/triggers", json={"t": 18.0}).json()["trigger"]
    ms = {m["id"]: m for m in client.get(f"/games/{gid}/moments").json()}
    voice, x, mine = ms["tr_0001"], ms["tr_0002"], ms[tap["id"]]
    assert (voice["kind"], voice["label"], voice["trigger"]) == (
        "bookmark",
        "Your clip (voice)",
        "voice",
    )
    assert (voice["t_start"], voice["t_end"], voice["t"], voice["clip_id"]) == (
        0.0,
        8.0,
        7.0,
        "c_0001",
    )
    assert voice["source"] == "heuristic" and voice["confirmed"] is False
    # no clip for the gesture in clips.json: the 8 s before it
    assert (x["label"], x["t_start"], x["t_end"], x["player"]["id"]) == (
        "Your clip (X sign)",
        9.0,
        17.0,
        "p1",
    )
    assert (mine["label"], mine["source"], mine["t_start"]) == ("Your clip", "user", 7.0)
    times = [m["t"] for m in client.get(f"/games/{gid}/moments").json()]
    assert times == sorted(times)


def test_voice_subject_follows_the_roster_and_clips_trim(client: TestClient):
    gid = _seed(client)
    clips = client.get(f"/games/{gid}/clips").json()["clips"]
    assert clips[0]["attribution"]["subject_player_id"] == "p2"  # "Alex" in game.json
    assert clips[0]["attribution"]["owner_player_id"] == "p2"
    assert [c["id"] for c in client.get(f"/games/{gid}/clips?player_id=p2").json()["clips"]] == [
        "c_0001"
    ]
    assert client.get(f"/games/{gid}/clips?player_id=p9").json()["clips"] == []

    r = client.patch(f"/games/{gid}/clips/c_0001", json={"t_start": 2.0, "t_end": 6.5})
    assert r.status_code == 200 and r.json()["source"] == "user" and r.json()["t_end"] == 6.5
    assert client.get(f"/games/{gid}/clips").json()["clips"][0]["t_start"] == 2.0
    bad = client.patch(f"/games/{gid}/clips/c_0001", json={"t_start": 5.0, "t_end": 4.0})
    assert bad.status_code == 400
    assert (
        client.patch(f"/games/{gid}/clips/c_0001", json={"t_start": 0, "t_end": 30}).status_code
        == 400
    )
    assert (
        client.patch(f"/games/{gid}/clips/c_9", json={"t_start": 0, "t_end": 1}).status_code == 404
    )


def test_score_from_events_and_user_corrections(client: TestClient):
    gid = _seed(client)
    # the fixture's shots carry no team/points: nothing scores yet
    assert client.get(f"/games/{gid}/score").json() == {
        "schema": "replay.score.v1",
        "score": [],
        "final": [0, 0],
    }
    r = client.patch(f"/games/{gid}/events/e_0001", json={"team": 0, "points": 3, "made": True})
    assert r.status_code == 200, r.text
    assert client.get(f"/games/{gid}/score").json()["final"] == [3, 0]

    r = client.post(f"/games/{gid}/score", json={"t": 1.0, "scores": [10, 12]})
    assert r.status_code == 201 and r.json()["source"] == "user"
    body = client.get(f"/games/{gid}/score").json()
    assert [(s["t"], s["scores"], s["source"]) for s in body["score"]] == [
        (1.0, [10, 12], "user"),
        (5.0, [13, 12], "auto"),
    ]
    stored = json.loads((client.app_settings.games_dir / gid / "score.json").read_text())
    assert stored["schema"] == "replay.score.v1" and len(stored["score"]) == 2
    assert client.post(f"/games/{gid}/score", json={"t": 1, "scores": [-1, 0]}).status_code == 400
