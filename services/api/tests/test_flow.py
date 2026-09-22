"""Fake-mode end to end: create -> upload -> calibrate -> process -> ready -> play.

No YOLO, no model weights: REPLAY_PIPELINE=fake copies the fixture output tree and
transcodes the upload with ffmpeg.
"""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from .conftest import CALIB, TINY_MP4, new_game


def poll_until_ready(client: TestClient, gid: str, timeout: float = 120.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        game = client.get(f"/games/{gid}").json()
        if game["status"] in ("ready", "failed"):
            return game
        time.sleep(0.25)
    raise AssertionError(f"game {gid} never left status={game['status']}")


def test_full_fake_pipeline_flow(client: TestClient):
    gid = new_game(client, "Fake mode run")

    up = client.put(f"/games/{gid}/upload", content=TINY_MP4.read_bytes())
    assert up.status_code == 200 and up.json()["size"] > 0

    cal = client.post(f"/games/{gid}/calibration", json=CALIB)
    assert cal.status_code == 200

    job = client.post(f"/games/{gid}/process")
    assert job.status_code == 202 and job.json()["status"] in ("queued", "running")

    game = poll_until_ready(client, gid)
    assert game["status"] == "ready", game
    assert set(game["stages"].values()) == {"done"}

    # identity survives processing; pipeline output is merged in
    assert game["id"] == gid and game["title"] == "Fake mode run"
    assert game["court"]["landmarks_px"]["rim"] == [641.1, 583.2]
    assert 19.5 < game["video"]["duration_s"] < 20.5  # probed from the transcode
    assert game["video"]["fps"] == 30.0
    assert [p["name"] for p in game["players"]] == ["Marcus", "Alex"]

    # media is playable and range-seekable
    wide = client.get(game["renditions"]["wide"], headers={"Range": "bytes=0-99"})
    assert wide.status_code == 206 and len(wide.content) == 100

    # a tracks chunk fetched exactly as the TV client would build the URL
    chunk_url = game["tracks"]["url_template"].format(chunk=1)
    chunk = client.get(chunk_url)
    assert chunk.status_code == 200
    body = chunk.json()
    assert body["schema"] == "replay.tracks.v1" and body["t0"] == 10.0
    assert body["frames"][0]["p"][0]["id"] == "p1"
    assert len(body["frames"]) == 100

    crops = client.get(game["croppaths"]["url_template"].format(player_id="p1"))
    assert crops.status_code == 200 and len(crops.json()["rects"]) == 600

    events = client.get(game["events_url"]).json()["events"]
    assert len([e for e in events if e["type"] == "shot"]) == 3

    # the library row the TV renders
    row = next(g for g in client.get("/games").json()["games"] if g["id"] == gid)
    assert row["status"] == "ready" and 19.5 < row["duration_s"] < 20.5

    # and the derived stats
    assert client.get(f"/games/{gid}/stats").json()["totals"]["attempted"] == 3


def test_job_state_survives_a_restart(client: TestClient, settings):
    """A job left running by a killed process must show up as failed, not stuck."""
    from replay_api.providers.jobs import LocalJobs

    jobs = LocalJobs(settings.jobs_state_path)
    job = jobs.submit("process", "g_x", lambda job_id: time.sleep(0.01))
    assert jobs.wait_idle(5)

    restarted = LocalJobs(settings.jobs_state_path)
    assert restarted.get(job["id"])["status"] == "done"

    jobs.state[job["id"]]["status"] = "running"
    jobs._flush()
    restarted = LocalJobs(settings.jobs_state_path)
    assert restarted.get(job["id"])["status"] == "failed"
    assert "restart" in restarted.get(job["id"])["error"]


def test_adapter_calls_courtcam_with_the_documented_contract(monkeypatch, tmp_path, settings):
    """Pins the courtcam entry point the adapter assumes (see pipeline_adapter docstring)."""
    import json

    import courtcam.pipeline as cp
    from replay_api import pipeline_adapter as adapter

    from .conftest import CALIB, FAKE_GAME

    seen = {}

    def fake_run(input_path, out_dir, **kw):
        seen.update(input=input_path, out=out_dir, **kw)
        kw["progress"]("ingest", 0.5)
        (out_dir / "game.json").write_text((FAKE_GAME / "game.json").read_text())
        return out_dir / "game.json"

    monkeypatch.setattr(cp, "run", fake_run)
    game = {
        "id": "g_abc",
        "title": "Real run",
        "sport": "basketball",
        "recorded_at": "2026-09-22T19:30:00-04:00",
        "renditions": None,
        "court": {"variant": "half", "standard": "fiba", "landmarks_px": CALIB["landmarks_px"]},
    }
    stages = []
    keys = adapter.run(
        input_path=tmp_path / "source.mp4",
        out_dir=tmp_path,
        game=game,
        progress=lambda s, f: stages.append((s, f)),
        pipeline="courtcam",
    )
    assert seen["sport"] == "basketball" and seen["variant"] == "half"
    assert seen["landmarks_px"]["rim"] == (641.1, 583.2)
    assert (seen["title"], seen["game_id"]) == ("Real run", "g_abc")
    assert seen["detector"] == "yolo" and seen["show_progress"] is False
    assert stages == [("ingest", 0.5)]
    assert set(keys) >= {"video", "players", "tracks", "croppaths", "events_url"}
    # the stub handed to courtcam must validate as replay.game.v1
    stub = json.loads((tmp_path / "game.json").read_text())
    assert stub["renditions"]["wide"] == "media/wide.mp4"
