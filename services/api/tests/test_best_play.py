"""The game's best play (GET/PUT/DELETE /games/{id}/best-play) and the phone's team pick
(PATCH /games/{id}/players/{pid} `team`). SYNTHETIC: the fake_game fixture (20 s, makes
at 5.0 by Marcus and 15.5 by Alex) plus a made-up hype.json."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient
from replay_api import moments

from .conftest import ready_game

HYPE = {"schema": "replay.hype.v1", "rate_hz": 2, "values": [],
        "candidates": [{"t": 6.0, "score": 0.9, "t_start": 3.0, "t_end": 7.0},
                       {"t": 14.0, "score": 0.5, "t_start": 12.0, "t_end": 16.0}]}  # fmt: skip


def _game(client: TestClient, duration: float | None = None, hype: bool = False) -> str:
    s = client.app_settings
    gid = ready_game(client, s)
    d = s.games_dir / gid
    if duration is not None:
        g = json.loads((d / "game.json").read_text())
        g["video"]["duration_s"] = duration
        (d / "game.json").write_text(json.dumps(g))
    if hype:
        (d / "hype.json").write_text(json.dumps(HYPE))
    return gid


def test_auto_game_winner_is_the_last_make_near_the_end(client: TestClient):
    gid = _game(client, hype=True)
    bp = client.get(f"/games/{gid}/best-play").json()["best_play"]
    assert bp["source"] == "auto:last_make" and bp["moment_id"] == "e_0003"
    assert bp["label"] == "Best play of the game" and bp["sub_label"] == "Game winner"
    assert bp["t"] == 15.5 and bp["t_start"] == 15.5 - moments.LEAD_S
    assert bp["t_end"] == 17.5 and bp["what"].endswith(", Alex")


def test_auto_falls_back_to_the_top_hype_play(client: TestClient):
    # 100 s video: the last make (15.5) is not in the final 30 s
    gid = _game(client, duration=100.0, hype=True)
    bp = client.get(f"/games/{gid}/best-play").json()["best_play"]
    assert bp["source"] == "auto:hype" and bp["sub_label"] is None
    assert (bp["t_start"], bp["t_end"]) == (3.0, 7.0)
    assert bp["moment_id"] == "e_0001" and bp["t"] == 5.0  # the basket inside it
    bare = _game(client, duration=100.0)  # no hype, no game winner: none
    assert client.get(f"/games/{bare}/best-play").json() == {"best_play": None}


def test_user_pick_wins_survives_and_can_be_dropped(client: TestClient):
    gid = _game(client, hype=True)
    body = {"t_start": 2.0, "t_end": 7.0, "t": 5.0, "moment_id": "e_0001"}
    r = client.put(f"/games/{gid}/best-play", json=body)
    assert r.status_code == 200, r.text
    bp = r.json()["best_play"]
    assert bp["source"] == "user" and bp["moment_id"] == "e_0001" and bp["sub_label"] is None
    assert (bp["t_start"], bp["t"], bp["t_end"]) == (2.0, 5.0, 7.0)
    edits = json.loads((client.app_settings.games_dir / gid / "edits.json").read_text())
    assert edits["best_play"]["moment_id"] == "e_0001"  # D-61: survives a re-run
    # a rename shows in the play's words at once
    client.patch(f"/games/{gid}/players/p1", json={"name": "Robin"})
    assert client.get(f"/games/{gid}/best-play").json()["best_play"]["what"].endswith(", Robin")
    # a second pick replaces the first
    r = client.put(f"/games/{gid}/best-play", json={"t_start": 10, "t_end": 12, "t": 11})
    assert r.json()["best_play"]["moment_id"] is None
    r = client.delete(f"/games/{gid}/best-play")
    assert r.status_code == 200 and r.json()["best_play"]["source"] == "auto:last_make"
    assert "best_play" not in json.loads(
        (client.app_settings.games_dir / gid / "edits.json").read_text()
    )


def test_user_pick_is_checked(client: TestClient):
    gid = _game(client)
    url = f"/games/{gid}/best-play"
    assert client.put(url, json={"t_start": 5, "t_end": 25, "t": 6}).status_code == 400
    assert client.put(url, json={"t_start": 5, "t_end": 4, "t": 4.5}).status_code == 400
    assert client.put(url, json={"t_start": 5, "t_end": 8, "t": 9}).status_code == 400
    assert client.put(url, json={"t_start": -1, "t_end": 8, "t": 2}).status_code == 422
    assert client.put("/games/nope/best-play", json={"t_start": 1, "t_end": 2, "t": 1.5}
                      ).status_code == 404  # fmt: skip
    assert client.get("/games/nope/best-play").status_code == 404


def test_player_team_pick(client: TestClient):
    gid = _game(client)
    r = client.patch(f"/games/{gid}/players/p1", json={"team": 1})
    assert r.status_code == 200, r.text
    p1 = next(p for p in r.json()["players"] if p["id"] == "p1")
    assert p1["team"] == 1 and p1["color_hex"] == "#E8E8E8" and "team_mixed" not in p1
    assert p1["name"] == "Marcus"  # a team pick keeps the name
    assert client.patch(f"/games/{gid}/players/p1", json={"team": 7}).status_code == 400
    assert client.patch(f"/games/{gid}/players/p1", json={}).status_code == 400


def test_team_tracking_never_saw_gets_a_contrasting_colour(client: TestClient):
    s = client.app_settings
    gid = _game(client)
    d = s.games_dir / gid
    g = json.loads((d / "game.json").read_text())
    g["teams"] = [{"id": 0, "color_hex": "#1F4FA0"}]  # every id read as one kit
    (d / "game.json").write_text(json.dumps(g))
    r = client.patch(f"/games/{gid}/players/p2", json={"team": 1})
    p2 = next(p for p in r.json()["players"] if p["id"] == "p2")
    assert p2["team"] == 1 and p2["color_hex"] == "#e8e8e8"  # light against a dark kit
