"""Media serving: HTTP Range (required for MP4 seeking, D-3), content types, traversal."""

from __future__ import annotations

from fastapi.testclient import TestClient

from .conftest import ready_game


def test_full_get_and_content_types(client: TestClient, settings):
    gid = ready_game(client, settings)
    r = client.get(f"/media/games/{gid}/media/wide.mp4")
    assert r.status_code == 200
    assert r.headers["content-type"] == "video/mp4"
    assert r.headers["accept-ranges"] == "bytes"

    assert client.get(f"/media/games/{gid}/events.json").headers["content-type"] == (
        "application/json"
    )
    assert client.get(f"/media/games/{gid}/media/thumb.jpg").status_code in (200, 404)


def test_range_request_returns_206_with_the_right_bytes(client: TestClient, settings):
    gid = ready_game(client, settings)
    path = settings.games_dir / gid / "media" / "wide.mp4"
    raw = path.read_bytes()

    r = client.get(f"/media/games/{gid}/media/wide.mp4", headers={"Range": "bytes=0-99"})
    assert r.status_code == 206
    assert r.content == raw[:100]
    assert r.headers["content-length"] == "100"
    assert r.headers["content-range"] == f"bytes 0-99/{len(raw)}"

    r = client.get(f"/media/games/{gid}/media/wide.mp4", headers={"Range": "bytes=1000-1099"})
    assert r.status_code == 206 and r.content == raw[1000:1100]

    r = client.get(f"/media/games/{gid}/media/wide.mp4", headers={"Range": "bytes=-50"})
    assert r.status_code == 206 and r.content == raw[-50:]


def test_unsatisfiable_range(client: TestClient, settings):
    gid = ready_game(client, settings)
    size = (settings.games_dir / gid / "media" / "wide.mp4").stat().st_size
    r = client.get(
        f"/media/games/{gid}/media/wide.mp4", headers={"Range": f"bytes={size + 10}-{size + 20}"}
    )
    assert r.status_code == 416


def test_no_directory_traversal(client: TestClient, settings):
    gid = ready_game(client, settings)
    (settings.data_dir / "secret.txt").write_text("nope")
    for path in ("../secret.txt", "..%2fsecret.txt", "tracks/../../secret.txt"):
        assert client.get(f"/media/games/{gid}/{path}").status_code == 404
    assert client.get(f"/media/games/{gid}/nope.json").status_code == 404
    assert client.get("/media/games/g_missing/events.json").status_code == 404
