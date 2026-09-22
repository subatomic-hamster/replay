"""D-9 / S-08: live stage progress is merged into the read path from the job record."""

from __future__ import annotations

import threading
import time

from fastapi.testclient import TestClient
from replay_api.config import Settings

from .conftest import CALIB, TINY_MP4, new_game, ready_game


def _blocking_job(client: TestClient, game_id: str, gate: threading.Event, stage: str | None):
    """Submit a `process` job that parks the worker so the read path can be observed."""
    jobs = client.app.state.jobs

    def task(job_id: str) -> None:
        if stage:
            jobs.progress(job_id, stage, 0.4)
        gate.wait(10)

    job = jobs.submit("process", game_id, task)
    deadline = time.time() + 5
    while time.time() < deadline:
        state = jobs.get(job["id"])
        if state["status"] == "running" and state.get("stage") == stage:
            return job
        time.sleep(0.02)
    raise AssertionError(f"job never reached stage {stage}: {jobs.get(job['id'])}")


def test_get_game_merges_running_stage_progress(client: TestClient, settings: Settings):
    gid = ready_game(client, settings)
    gate = threading.Event()
    try:
        _blocking_job(client, gid, gate, "detect")
        game = client.get(f"/games/{gid}").json()
        assert game["status"] == "processing"
        assert game["stages"] == {
            "ingest": "done",
            "detect": "running",
            "track": "pending",
            "render": "pending",
            "label": "pending",
        }
        assert game["progress"] == {
            "ingest": 1.0,
            "detect": 0.4,
            "track": 0.0,
            "render": 0.0,
            "label": 0.0,
        }
        # GET /games carries the same merged view (the library shows "detecting…")
        row = next(g for g in client.get("/games").json() if g["id"] == gid)
        assert row["status"] == "processing" and row["stages"]["detect"] == "running"
        assert row["progress"]["detect"] == 0.4
    finally:
        gate.set()
    assert client.app.state.jobs.wait_idle(5)

    # once the job is done, game.json is the truth again
    after = client.get(f"/games/{gid}").json()
    assert after["status"] == "ready" and "progress" not in after


def test_queued_job_reports_processing_with_every_stage_pending(
    client: TestClient, settings: Settings
):
    gid = ready_game(client, settings)
    gate = threading.Event()
    try:
        _blocking_job(client, gid, gate, "ingest")  # occupies the single worker thread
        client.app.state.jobs.submit("process", gid, lambda _job_id: None)  # stays queued
        game = client.get(f"/games/{gid}").json()
        # the newest active job is the queued one: nothing has reported a stage yet
        assert game["status"] == "processing"
        assert set(game["stages"].values()) == {"pending"}
    finally:
        gate.set()
    assert client.app.state.jobs.wait_idle(5)


def test_process_is_idempotent_while_a_job_is_active(client: TestClient, settings: Settings):
    gid = new_game(client, "Double tap")
    assert client.put(f"/games/{gid}/upload", content=TINY_MP4.read_bytes()).status_code == 200
    assert client.post(f"/games/{gid}/calibration", json=CALIB).status_code == 200

    gate = threading.Event()
    try:
        first = _blocking_job(client, gid, gate, "ingest")
        again = client.post(f"/games/{gid}/process")
        assert again.status_code == 202
        assert again.json() == {"job_id": first["id"], "status": "running", "game_id": gid}
        assert len(client.app.state.jobs.for_game(gid)) == 1
    finally:
        gate.set()
    assert client.app.state.jobs.wait_idle(5)


def test_ws_accepts_the_pairing_code_as_well_as_the_session_id(client: TestClient):
    session = client.post("/sessions").json()
    with (
        client.websocket_connect(f"/sessions/{session['id']}") as tv,
        client.websocket_connect(f"/sessions/{session['code']}") as phone,
    ):
        phone.send_text('{"type":"query","text":"Marcus — all shots"}')
        assert tv.receive_text() == '{"type":"query","text":"Marcus — all shots"}'
