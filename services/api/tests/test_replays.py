"""M8: replays/<play>/manifest.json + angle videos are listed and served."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from .conftest import TINY_MP4, ready_game


def _manifest(gd, play_id: str, t_start: float, angles: list[tuple[str, str]]) -> None:
    d = gd / "replays" / play_id
    d.mkdir(parents=True)
    for stem, _ in angles:
        (d / f"{stem}.mp4").write_bytes(TINY_MP4.read_bytes())
    doc = {
        "schema": "replay.replay_manifest.v1",
        "play_id": play_id,
        "label": f"Shot {play_id}",
        "sport": "basketball",
        "t_start": t_start,
        "t_end": t_start + 6.0,
        "source": "plays",
        "synthetic": True,
        "angles": [
            {
                "id": aid,
                "tier": "B" if stem in ("orbit", "push_in") else "A",
                "label": stem,
                "url": f"replays/{play_id}/{stem}.mp4",
                "duration_s": 6.0,
                "width": 1280,
                "height": 720,
            }
            for stem, aid in angles
        ],
        "commentary": None,
    }
    (d / "manifest.json").write_text(json.dumps(doc))


def test_no_replays_until_rendered(client: TestClient, settings):
    gid = ready_game(client, settings)
    assert client.get(f"/games/{gid}/replays").json() == {"game_id": gid, "replays": []}
    assert client.get(f"/games/{gid}/replays/pl_0001").status_code == 404


def test_replays_listed_in_time_order_and_manifest_urls_resolved(client: TestClient, settings):
    gid = ready_game(client, settings)
    gd = settings.games_dir / gid
    _manifest(gd, "pl_0002", 20.0, [("wide", "wide"), ("orbit", "orbit")])
    _manifest(
        gd, "pl_0001", 4.0, [("wide", "wide"), ("follow_p4", "follow:p4"), ("push_in", "push_in")]
    )

    listed = client.get(f"/games/{gid}/replays").json()["replays"]
    assert [r["play_id"] for r in listed] == ["pl_0001", "pl_0002"]
    assert [r["angles"] for r in listed] == [3, 2]
    m = client.get(listed[0]["manifest_url"]).json()
    assert m["schema"] == "replay.replay_manifest.v1" and m["game_id"] == gid
    assert [a["id"] for a in m["angles"]] == ["wide", "follow:p4", "push_in"]
    assert [a["tier"] for a in m["angles"]] == ["A", "A", "B"]
    url = m["angles"][2]["url"]
    assert url.endswith(f"/media/games/{gid}/replays/pl_0001/push_in.mp4")
    r = client.get(url, headers={"Range": "bytes=0-49"})
    assert r.status_code == 206 and r.content == TINY_MP4.read_bytes()[:50]


def test_replay_routes_404_and_traversal(client: TestClient, settings):
    assert client.get("/games/g_nope/replays").status_code == 404
    gid = ready_game(client, settings)
    assert client.get(f"/games/{gid}/replays/..%2F..%2Fgame").status_code == 404
