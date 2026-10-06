"""M6: the broadcast rendition and cuts.json are advertised once the worker wrote them."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from .conftest import TINY_MP4, ready_game


def test_broadcast_absent_until_rendered(client: TestClient, settings):
    gid = ready_game(client, settings)
    g = client.get(f"/games/{gid}").json()
    assert g["renditions"]["broadcast"] is None and g["cuts_url"] is None
    r = client.get(f"/games/{gid}/renditions").json()
    assert [x["id"] for x in r["renditions"]] == ["wide"]


def test_broadcast_listed_and_served_with_range(client: TestClient, settings):
    gid = ready_game(client, settings)
    gd = settings.games_dir / gid
    (gd / "renditions").mkdir()
    (gd / "renditions" / "broadcast.mp4").write_bytes(TINY_MP4.read_bytes())
    (gd / "cuts.json").write_text(json.dumps({"schema": "replay.cuts.v1", "cuts": []}))

    g = client.get(f"/games/{gid}").json()
    assert g["renditions"]["broadcast"].endswith(f"/media/games/{gid}/renditions/broadcast.mp4")
    assert g["cuts_url"].endswith(f"/media/games/{gid}/cuts.json")

    listed = client.get(f"/games/{gid}/renditions").json()["renditions"]
    assert [x["kind"] for x in listed] == ["wide", "broadcast"]
    b = listed[-1]
    assert b["url"] == g["renditions"]["broadcast"] and b["cuts_url"] == g["cuts_url"]

    r = client.get(b["url"], headers={"Range": "bytes=0-99"})
    assert r.status_code == 206 and r.content == TINY_MP4.read_bytes()[:100]
    assert r.headers["content-type"] == "video/mp4"
    assert client.get(b["cuts_url"]).json()["schema"] == "replay.cuts.v1"


def test_renditions_404_for_unknown_game(client: TestClient):
    assert client.get("/games/g_nope/renditions").status_code == 404
