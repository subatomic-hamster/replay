"""2.5D scene packages (replay.scene_package.v1): listed, layout served with absolute
file URLs, files through /media with HTTP Range. Uses the committed synthetic fixture
package (fixtures/scene_synth, built by the worker's `scene` stage)."""

from __future__ import annotations

import json
import shutil

from fastapi.testclient import TestClient

from .conftest import FIXTURES, ready_game

PKG = FIXTURES / "scene_synth"


def _install(gd) -> str:
    lay = json.loads((PKG / "layout.json").read_text())
    shutil.copytree(PKG, gd / "replays" / lay["play_id"] / "scene")
    return lay["play_id"]


def test_no_scenes_until_built(client: TestClient, settings):
    gid = ready_game(client, settings)
    assert client.get(f"/games/{gid}/scenes").json() == {"game_id": gid, "scenes": []}
    assert client.get(f"/games/{gid}/scenes/pl_0001").status_code == 404


def test_scene_listed_layout_resolved_and_atlas_ranged(client: TestClient, settings):
    gid = ready_game(client, settings)
    pid = _install(settings.games_dir / gid)
    listed = client.get(f"/games/{gid}/scenes").json()["scenes"]
    assert [s["play_id"] for s in listed] == [pid]
    assert listed[0]["schema"] == "replay.scene_package.v1" and listed[0]["synthetic"] is True
    lay = client.get(listed[0]["layout_url"]).json()
    assert lay["game_id"] == gid and lay["n_frames"] == len(lay["frames"])
    atlas = lay["atlas"]["url"]
    assert atlas.endswith(f"/media/games/{gid}/replays/{pid}/scene/atlas.mp4")
    r = client.get(atlas, headers={"Range": "bytes=0-99"})
    assert r.status_code == 206 and r.content == (PKG / "atlas.mp4").read_bytes()[:100]
    for plate in lay["plates"]:
        got = client.get(plate["url"])
        assert got.status_code == 200 and got.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_replay_manifest_points_at_its_scene(client: TestClient, settings):
    gid = ready_game(client, settings)
    gd = settings.games_dir / gid
    pid = _install(gd)
    doc = {"schema": "replay.replay_manifest.v1", "play_id": pid, "label": "x", "angles": []}
    (gd / "replays" / pid / "manifest.json").write_text(json.dumps(doc))
    m = client.get(f"/games/{gid}/replays/{pid}").json()
    assert m["scene_url"].endswith(f"/games/{gid}/scenes/{pid}")


def test_scene_routes_404_and_traversal(client: TestClient, settings):
    assert client.get("/games/g_nope/scenes").status_code == 404
    gid = ready_game(client, settings)
    assert client.get(f"/games/{gid}/scenes/..%2F..%2Fgame").status_code == 404
