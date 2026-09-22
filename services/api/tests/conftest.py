from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from replay_api.config import Settings, from_env
from replay_api.main import create_app

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
FAKE_GAME = FIXTURES / "fake_game"
TINY_MP4 = FIXTURES / "tiny.mp4"

CALIB = {
    "sport": "basketball",
    "variant": "half",
    # projected from courtcam's basketball_half template: reprojection error ~0.02 px
    "landmarks_px": {
        "corner_nl": [180.0, 660.0],
        "corner_nr": [1100.0, 660.0],
        "corner_fl": [430.0, 300.0],
        "corner_fr": [860.0, 300.0],
        "rim": [641.1, 583.2],
    },
}


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    # explicit overrides so a developer's own REPLAY_* env cannot change a test result
    return from_env(
        api_key=None,
        data_dir=tmp_path / "data",
        pipeline="fake",
        fake_pipeline_dir=FAKE_GAME,
        cors_origins=["*"],
        storage="local",
        jobs="local",
        labeler="heuristic",
        query="rules",
    )


@pytest.fixture
def client(settings: Settings) -> TestClient:
    with TestClient(create_app(settings)) as c:
        c.app_settings = settings  # type: ignore[attr-defined]
        yield c


def new_game(client: TestClient, title: str = "Tuesday run") -> str:
    r = client.post("/games", json={"title": title, "sport": "basketball"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def ready_game(client: TestClient, settings: Settings, title: str = "Fixture game") -> str:
    """A processed game, seeded straight from the fixture tree (no pipeline run)."""
    gid = new_game(client, title)
    dst = settings.games_dir / gid
    shutil.copytree(FAKE_GAME, dst, dirs_exist_ok=True)
    (dst / "media").mkdir(exist_ok=True)
    shutil.copyfile(TINY_MP4, dst / "media" / "wide.mp4")
    (dst / "media" / "thumb.jpg").write_bytes(b"\xff\xd8\xff\xdb placeholder jpeg")
    game = json.loads((dst / "game.json").read_text())
    game["id"], game["title"] = gid, title
    (dst / "game.json").write_text(json.dumps(game))
    return gid
