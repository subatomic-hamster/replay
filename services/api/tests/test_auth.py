"""REPLAY_API_KEY unset -> open; set -> X-Replay-Key required everywhere but media/healthz."""

from __future__ import annotations

import dataclasses

import pytest
from fastapi.testclient import TestClient
from replay_api.main import create_app


@pytest.fixture
def keyed(settings):
    with TestClient(create_app(dataclasses.replace(settings, api_key="s3cret"))) as c:
        yield c


def test_auth_disabled_by_default(client: TestClient):
    assert client.get("/games").status_code == 200


def test_key_required(keyed: TestClient):
    assert keyed.get("/games").status_code == 401
    assert keyed.get("/games").json()["detail"]
    assert keyed.post("/games", json={"title": "x"}).status_code == 401
    assert keyed.get("/games", headers={"X-Replay-Key": "wrong"}).status_code == 401
    assert keyed.get("/games", headers={"X-Replay-Key": "s3cret"}).status_code == 200


def test_media_and_healthz_stay_open(keyed: TestClient, settings):
    assert keyed.get("/healthz").status_code == 200
    gid = keyed.post("/games", json={"title": "x"}, headers={"X-Replay-Key": "s3cret"}).json()["id"]
    media = settings.games_dir / gid / "media"
    media.mkdir(parents=True, exist_ok=True)
    (media / "wide.mp4").write_bytes(b"0123456789")
    assert keyed.get(f"/media/games/{gid}/media/wide.mp4").status_code == 200
