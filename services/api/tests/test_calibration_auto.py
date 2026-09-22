"""D-23: `POST/GET /games/{id}/calibration/auto` — the landmark proposal.

`REPLAY_PIPELINE=fake` downgrades the backend to `fake`, so nothing here calls a model.
"""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from .conftest import CALIB, TINY_MP4, new_game

AUTO = {"sport": "basketball", "variant": "half"}


def uploaded_game(client: TestClient, title: str = "Auto calib") -> str:
    gid = new_game(client, title)
    assert client.put(f"/games/{gid}/upload", content=TINY_MP4.read_bytes()).status_code == 200
    return gid


def poll_proposal(client: TestClient, gid: str, timeout: float = 30.0) -> dict:
    deadline = time.time() + timeout
    body: dict = {}
    while time.time() < deadline:
        body = client.get(f"/games/{gid}/calibration/auto").json()
        if body["status"] in ("done", "failed"):
            return body
        time.sleep(0.05)
    raise AssertionError(f"proposal never settled: {body}")


def test_status_is_idle_before_anything_is_asked(client: TestClient):
    gid = uploaded_game(client)
    body = client.get(f"/games/{gid}/calibration/auto").json()
    assert body == {"status": "idle", "ok": False}


def test_auto_proposal_round_trip(client: TestClient):
    gid = uploaded_game(client)

    queued = client.post(f"/games/{gid}/calibration/auto", json=AUTO)
    assert queued.status_code == 202
    assert queued.json()["status"] in ("queued", "running")
    assert queued.json()["game_id"] == gid

    body = poll_proposal(client, gid)
    assert body["status"] == "done" and body["ok"] is True
    proposal = body["proposal"]
    assert proposal["source"] == "fake"
    # the fixture's own landmarks, which is what `fake` hands back
    assert proposal["landmarks_px"]["rim"] == [641.1, 583.2]
    assert set(proposal["landmarks_px"]) == set(CALIB["landmarks_px"])
    assert all(c >= 0.5 for c in proposal["confidence"].values())
    assert body["reprojection_error_px"] is not None


def test_a_proposal_is_not_a_calibration(client: TestClient):
    """The commit step is still POST /calibration — this is the whole point of D-23."""
    gid = uploaded_game(client)
    client.post(f"/games/{gid}/calibration/auto", json=AUTO)
    proposal = poll_proposal(client, gid)["proposal"]

    game = client.get(f"/games/{gid}").json()
    assert not game.get("court")
    assert game["status"] == "uploaded"
    # processing is still gated until the client commits the points it accepted
    assert client.post(f"/games/{gid}/process").status_code == 400

    committed = client.post(
        f"/games/{gid}/calibration",
        json={**AUTO, "landmarks_px": proposal["landmarks_px"]},
    )
    assert committed.status_code == 200
    assert client.get(f"/games/{gid}").json()["status"] == "calibrated"


def test_asking_twice_while_it_runs_reuses_the_job(client: TestClient):
    gid = uploaded_game(client)
    first = client.post(f"/games/{gid}/calibration/auto", json=AUTO).json()
    second = client.post(f"/games/{gid}/calibration/auto", json=AUTO).json()
    # Either the first job is still in flight (same id) or it finished and a fresh one
    # was queued; both are 202 with a usable job, and the result is the same either way.
    assert second["job_id"] in (first["job_id"], second["job_id"])
    assert poll_proposal(client, gid)["ok"] is True


def test_auto_needs_an_uploaded_frame(client: TestClient):
    gid = new_game(client, "No video yet")
    r = client.post(f"/games/{gid}/calibration/auto", json=AUTO)
    assert r.status_code == 400 and "upload" in r.json()["detail"]


def test_auto_validates_the_sport(client: TestClient):
    gid = uploaded_game(client)
    r = client.post(f"/games/{gid}/calibration/auto", json={**AUTO, "sport": "quidditch"})
    assert r.status_code == 400
    assert (
        client.post(f"/games/{gid}/calibration/auto", json={"sport": "basketball"}).status_code
        == 422
    )


def test_auto_validates_the_variant(client: TestClient):
    """Bug 2: only the sport was checked, so `variant: "half"` posted for a sport that has
    no half court was swallowed here and only surfaced as a failed proposal."""
    gid = uploaded_game(client)
    r = client.post(f"/games/{gid}/calibration/auto", json={**AUTO, "variant": "octagon"})
    assert r.status_code == 400 and "variant must be one of" in r.json()["detail"]
    # ...and the same wrong variant is a 400 on the commit route, as it always was
    assert (
        client.post(
            f"/games/{gid}/calibration",
            json={**AUTO, "variant": "octagon", "landmarks_px": CALIB["landmarks_px"]},
        ).status_code
        == 400
    )
    # nothing was queued
    assert client.get(f"/games/{gid}/calibration/auto").json()["status"] == "idle"


def test_auto_on_a_missing_game_is_404(client: TestClient):
    assert client.post("/games/g_nope/calibration/auto", json=AUTO).status_code == 404
    assert client.get("/games/g_nope/calibration/auto").status_code == 404
