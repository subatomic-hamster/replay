"""D-80 cloud mode against a fake S3/SSM (moto's server, so presigned URLs are real HTTP):
upload tokens, multipart upload, media redirects, the /worker API and the remote runner."""

from __future__ import annotations

import base64
import dataclasses
import json
import logging
import time

import httpx
import pytest
from fastapi.testclient import TestClient
from replay_api import auth
from replay_api.main import create_app

from .conftest import CALIB, TINY_MP4

boto3 = pytest.importorskip("boto3")
moto_server = pytest.importorskip("moto.server")

BUCKET = "replay-test"
KEY, WORKER, SECRET = "api-k3y", "w0rker", "t0ken-secret"


@pytest.fixture(scope="module")
def moto_url():
    server = moto_server.ThreadedMotoServer(ip_address="127.0.0.1", port=0)
    server.start()
    host, port = server.get_host_and_port()
    yield f"http://{host}:{port}"
    server.stop()


@pytest.fixture
def aws(moto_url, monkeypatch):
    for k, v in {"AWS_ENDPOINT_URL": moto_url, "AWS_ACCESS_KEY_ID": "testing",
                 "AWS_SECRET_ACCESS_KEY": "testing", "AWS_DEFAULT_REGION": "us-east-1",
                 "AWS_REGION": "us-east-1"}.items():  # fmt: skip
        monkeypatch.setenv(k, v)
    httpx.post(f"{moto_url}/moto-api/reset")
    s3 = boto3.client("s3")
    s3.create_bucket(Bucket=BUCKET)
    return s3


@pytest.fixture
def cloud_settings(settings, aws):
    return dataclasses.replace(
        settings, storage="s3", jobs="s3", s3_bucket=BUCKET, api_key=KEY, worker_key=WORKER,
        upload_token_secret=SECRET, public_web_base="https://replay.example/",
    )  # fmt: skip


@pytest.fixture
def cloud(cloud_settings):
    with TestClient(create_app(cloud_settings), headers={"X-Replay-Key": KEY}) as c:
        yield c


def _game(cloud: TestClient) -> dict:
    r = cloud.post("/games", json={"title": "QR run", "sport": "basketball"})
    assert r.status_code == 201, r.text
    return r.json()


def _upload(cloud: TestClient, gid: str, headers=None, data: bytes | None = None,
            status: int = 200) -> dict:  # fmt: skip
    data = TINY_MP4.read_bytes() if data is None else data
    r = cloud.post(f"/games/{gid}/upload/multipart", headers=headers,
                   json={"size": len(data), "content_type": "video/mp4"})  # fmt: skip
    assert r.status_code == 200, r.text
    init = r.json()
    size = init["part_size"]
    parts = []
    for p in init["parts"]:
        chunk = data[(p["n"] - 1) * size : p["n"] * size]
        put = httpx.put(p["url"], content=chunk)
        assert put.status_code == 200, put.text
        parts.append({"n": p["n"], "etag": put.headers["etag"]})
    r = cloud.post(f"/games/{gid}/upload/complete", headers=headers,
                   json={"upload_id": init["upload_id"], "parts": parts})  # fmt: skip
    assert r.status_code == status, r.text
    return r.json()


def _tamper(token: str) -> str:
    raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode()
    gid, exp, mac = raw.rsplit(".", 2)
    forged = f"{gid}.{int(exp) + 86400}.{mac}".encode()  # a longer life, same signature
    return base64.urlsafe_b64encode(forged).decode().rstrip("=")


def test_create_game_returns_the_qr_fields(cloud):
    g = _game(cloud)
    assert g["upload"] == {"mode": "multipart"}
    assert g["upload_page_url"] == f"https://replay.example/u/{g['id']}#t={g['upload_token']}"
    assert auth.token_game(SECRET, g["upload_token"]) == g["id"]


def test_upload_token_accept_and_reject(cloud):
    a, b = _game(cloud), _game(cloud)
    anon = TestClient(cloud.app)
    tok = {"X-Replay-Upload-Token": a["upload_token"]}
    assert anon.get(f"/games/{a['id']}", headers=tok).status_code == 200
    assert anon.get(f"/games/{a['id']}/jobs", headers=tok).json() == []
    assert anon.get("/sports", headers=tok).status_code == 200
    # wrong game, a route the phone has no business on, no token
    assert anon.get(f"/games/{b['id']}", headers=tok).status_code == 401
    assert anon.get("/games", headers=tok).status_code == 401
    assert anon.post(f"/games/{a['id']}/events", json={"t": 1}, headers=tok).status_code == 401
    assert anon.get(f"/games/{a['id']}").status_code == 401
    # expired, tampered, signed with another secret
    old = auth.make_token(SECRET, a["id"], now=time.time() - auth.TTL_S - 5)
    for bad in (old, _tamper(a["upload_token"]), auth.make_token("nope", a["id"]), "garbage!"):
        r = anon.get(f"/games/{a['id']}", headers={"X-Replay-Upload-Token": bad})
        assert r.status_code == 401, bad


def test_multipart_upload_grabs_the_calibration_frame(cloud, aws):
    g = _game(cloud)
    gid = g["id"]
    tok = {"X-Replay-Upload-Token": g["upload_token"]}
    game = _upload(TestClient(cloud.app), gid, headers=tok)
    assert game["status"] == "uploaded" and game["calib_url"]
    head = aws.head_object(Bucket=BUCKET, Key=f"games/{gid}/source.mp4")
    assert head["ContentLength"] == TINY_MP4.stat().st_size
    jpg = aws.get_object(Bucket=BUCKET, Key=f"games/{gid}/media/calib.jpg")["Body"].read()
    assert jpg[:2] == b"\xff\xd8"
    # abort of an unknown upload is a clean 400
    assert cloud.post(f"/games/{gid}/upload/abort", json={"upload_id": "nope"}).status_code == 400


def test_multipart_parts_cover_the_file_in_order(cloud, aws):
    """Part n is bytes [(n-1)*part_size, n*part_size); complete returns the Game."""
    gid = _game(cloud)["id"]
    big = cloud.post(f"/games/{gid}/upload/multipart", json={"size": 20 << 30}).json()
    assert big["part_size"] == 32 << 20 and len(big["parts"]) == 640
    data = b"\0\0\0\x18ftypisom" + bytes(range(256)) * ((17 << 20) // 256)
    game = _upload(cloud, gid, data=data)
    assert game["id"] == gid and game["status"] == "uploaded" and "sport_ui" in game
    assert game["calib_url"] is None  # not decodable: no frame, still uploaded
    got = aws.get_object(Bucket=BUCKET, Key=f"games/{gid}/source.mp4")["Body"].read()
    assert got == data


def test_non_mp4_upload_is_refused_before_decoding(cloud, aws):
    """An HLS playlist could make FFmpeg open file:// or another host: 415, and gone."""
    gid = _game(cloud)["id"]
    playlist = b"#EXTM3U\n#EXT-X-TARGETDURATION:1\n#EXTINF:1,\nfile:///etc/passwd\n"
    r = _upload(cloud, gid, data=playlist, status=415)
    assert "MP4" in r["detail"]
    assert "Contents" not in aws.list_objects_v2(Bucket=BUCKET, Prefix=f"games/{gid}/source")
    assert cloud.get(f"/games/{gid}").json()["status"] == "created"


def test_frame_grab_decodes_mp4_only(cloud, aws, tmp_path):
    """Even past the ftyp check, the capture is mov-demuxer-only: a playlist naming a
    local file yields no frame, the same video as an MP4 does."""
    from replay_api import pipeline_adapter as adapter

    st = cloud.app.state.storage
    m3u8 = (f"#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:20\n#EXTINF:20.0,\n"
            f"file://{TINY_MP4}\n#EXT-X-ENDLIST\n").encode()  # fmt: skip
    aws.put_object(Bucket=BUCKET, Key="games/g_0/list.m3u8", Body=m3u8)
    aws.put_object(Bucket=BUCKET, Key="games/g_0/v.mp4", Body=TINY_MP4.read_bytes())
    assert not adapter.grab_frame_url(st.presign_get("g_0", "list.m3u8"), tmp_path / "a.jpg")
    assert adapter.grab_frame_url(st.presign_get("g_0", "v.mp4"), tmp_path / "b.jpg")
    assert not adapter.grab_frame_url(f"file://{TINY_MP4}", tmp_path / "c.jpg")


def test_single_request_upload_is_local_only(cloud, client, settings):
    gid = _game(cloud)["id"]
    assert cloud.put(f"/games/{gid}/upload", content=b"x").status_code == 409
    files = {"file": ("a.mp4", b"x", "video/mp4")}
    assert cloud.post(f"/games/{gid}/upload", files=files).status_code == 409
    # local mode: multipart says 409, and the phone falls back to the PUT with its token
    lgid = client.post("/games", json={"title": "x"}).json()["id"]
    assert client.post(f"/games/{lgid}/upload/multipart", json={"size": 10}).status_code == 409
    keyed = dataclasses.replace(settings, api_key="s3cret", upload_token_secret="sec")
    with TestClient(create_app(keyed)) as c:
        g = c.post("/games", json={"title": "x"}, headers={"X-Replay-Key": "s3cret"}).json()
        assert g["upload"] == {"mode": "put", "url": g["upload_url"]}
        tok = {"X-Replay-Upload-Token": g["upload_token"]}
        r = c.put(f"/games/{g['id']}/upload", content=TINY_MP4.read_bytes(), headers=tok)
        assert r.status_code == 200 and r.json()["status"] == "uploaded"
        assert c.put(f"/games/{g['id']}/upload", content=b"x").status_code == 401


def test_media_redirects_to_presigned_s3(cloud, aws):
    gid = _game(cloud)["id"]
    aws.put_object(Bucket=BUCKET, Key=f"games/{gid}/media/wide.mp4", Body=b"0123456789")
    r = TestClient(cloud.app).get(f"/media/games/{gid}/media/wide.mp4", follow_redirects=False)
    assert r.status_code == 302
    got = httpx.get(r.headers["location"], headers={"Range": "bytes=2-5"})
    assert got.status_code == 206 and got.content == b"2345"
    assert got.headers["content-type"] == "video/mp4"
    # encoded, so the client does not normalise the dots away before the route sees them
    escape = f"/media/games/{gid}/media/%2E%2E/%2E%2E/x"
    assert cloud.get(escape, follow_redirects=False).status_code == 404
    # the raw upload is private: no presigned link for it on the open /media route
    aws.put_object(Bucket=BUCKET, Key=f"games/{gid}/source.mp4", Body=b"raw")
    for rel in ("source.mp4", "media/../source.mp4", "./source.mp4"):
        r = TestClient(cloud.app).get(f"/media/games/{gid}/{rel}", follow_redirects=False)
        assert r.status_code == 404, rel


def test_media_redirect_is_cacheable(cloud, aws, monkeypatch):
    """The 302 target is one URL per hour window (so the TV's and browsers' caches hit),
    the 302 says how long it holds, versioned images are immutable and the rest is
    revalidated; a changed image gets a new `?v=` and so a new URL."""
    gid = _game(cloud)["id"]
    aws.put_object(Bucket=BUCKET, Key=f"games/{gid}/media/hero.jpg", Body=b"\xff\xd8one")
    aws.put_object(Bucket=BUCKET, Key=f"games/{gid}/events.json", Body=b"{}")
    t0 = 1_800_000_000 - 1_800_000_000 % 3600 + 600  # 10 min into an hour window
    clock = {"t": t0}
    monkeypatch.setattr("replay_api.cloud._now", lambda: clock["t"])
    media = TestClient(cloud.app)

    def hop(path: str):
        r = media.get(path, follow_redirects=False)
        assert r.status_code == 302, r.text
        return r.headers["location"], r.headers["cache-control"]

    a, cc = hop(f"/media/games/{gid}/media/hero.jpg")
    clock["t"] += 1500
    b, cc2 = hop(f"/media/games/{gid}/media/hero.jpg")
    assert a == b and "X-Amz-Date=20270115T080000Z" in a  # signed at the window start
    assert (cc, cc2) == ("public, max-age=3000", "public, max-age=1500")
    clock["t"] += 1500  # next window: a new URL
    assert hop(f"/media/games/{gid}/media/hero.jpg")[0] != a

    # the game names the hero with its ETag; that URL's bytes are immutable
    hero_url = cloud.get(f"/games/{gid}").json()["hero_url"]
    etag = aws.head_object(Bucket=BUCKET, Key=f"games/{gid}/media/hero.jpg")["ETag"].strip('"')
    assert hero_url.endswith(f"/media/hero.jpg?v={etag[:16]}")
    v1, _ = hop(hero_url)
    got = httpx.get(v1)
    assert got.content == b"\xff\xd8one" and "immutable" in got.headers["cache-control"]
    assert v1 == hop(hero_url)[0]
    aws.put_object(Bucket=BUCKET, Key=f"games/{gid}/media/hero.jpg", Body=b"\xff\xd8two")
    hero2 = cloud.get(f"/games/{gid}").json()["hero_url"]
    assert hero2 != hero_url and httpx.get(hop(hero2)[0]).content == b"\xff\xd8two"
    # unversioned and JSON: revalidated on every use, never served stale
    plain = httpx.get(hop(f"/media/games/{gid}/events.json")[0])
    assert plain.status_code == 200 and plain.headers["cache-control"] == "no-cache"
    # the old behaviour, behind REPLAY_MEDIA_SIGN_WINDOW_S=0
    cloud.app.state.settings = dataclasses.replace(cloud.app.state.settings, media_sign_window_s=0)
    assert hop(f"/media/games/{gid}/events.json")[1] == "no-store"


def test_json_state_is_never_stale(cloud, aws):
    """Another Lambda instance (here: a direct S3 write) changes game.json between calls."""
    gid = _game(cloud)["id"]
    assert cloud.get(f"/games/{gid}").json()["title"] == "QR run"
    doc = json.loads(aws.get_object(Bucket=BUCKET, Key=f"games/{gid}/game.json")["Body"].read())
    aws.put_object(Bucket=BUCKET, Key=f"games/{gid}/game.json",
                   Body=json.dumps({**doc, "title": "Renamed"}).encode())  # fmt: skip
    assert cloud.get(f"/games/{gid}").json()["title"] == "Renamed"
    assert [g["title"] for g in cloud.get("/games").json()] == ["Renamed"]
    # a raw-file write in a route (edits.json via a bookmark) is written back to S3
    assert cloud.post(f"/games/{gid}/events", json={"t": 4.0}).status_code == 201
    edits = aws.get_object(Bucket=BUCKET, Key=f"games/{gid}/edits.json")["Body"].read()
    assert b"bookmark" in edits


# D-86: folders no route below reads (moment thumbs, storyboard tiles)
JUNK = ("moments", "storyboard")
VID = "v_0123456789ab"


def _full_game(cloud: TestClient, aws) -> tuple[str, object]:
    """A processed game in S3: docs, a track chunk, a vertical export spec, and folders of
    images (`JUNK`) that a whole-game pull would download, one GET each."""
    gid = _game(cloud)["id"]

    def put(rel: str, body) -> None:
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        aws.put_object(Bucket=BUCKET, Key=f"games/{gid}/{rel}", Body=data)

    key = f"games/{gid}/game.json"
    doc = json.loads(aws.get_object(Bucket=BUCKET, Key=key)["Body"].read())
    put("game.json", {**doc, "status": "ready",
                      "players": [{"id": "p1", "name": None, "team": 0}]})  # fmt: skip
    shot = {"id": "e_1", "type": "shot", "t_key": 3.0, "t_start": 2.0, "t_end": 4.0,
            "confidence": 0.9, "made": None, "player_id": "p1"}  # fmt: skip
    put("events.json", {"events": [shot]})
    p1 = {"id": "p1", "bb": [0.4, 0.4, 0.1, 0.3], "ct": [5.0, 5.0]}
    put("tracks/000000.json", {"frames": [{"t": 3.0, "p": [p1]}]})
    put(f"exports/vertical/{VID}.json", {"id": VID, "t_start": 2.0, "t_end": 4.0})
    for d in JUNK:
        for i in range(10):
            put(f"{d}/x_{i}.jpg", b"\xff\xd8 jpeg")
    return gid, put


def _pulled_junk(cloud: TestClient, gid: str) -> list[str]:
    root = cloud.app.state.storage.games_dir / gid
    return [str(p) for d in JUNK for p in (root / d).glob("x_*.jpg")]


# every GET the TV makes when a game opens (Watch, its Stats and Review), the phone's
# score, condensed and exports reads
GAME_READS = ["", "/hype", "/rallies", "/condensed", "/score", "/commentary", "/moments",
              "/storyboard", "/stats", "/review/queue", "/renditions", "/replays",
              "/exports/vertical"]  # fmt: skip


@pytest.mark.parametrize("route", GAME_READS)
def test_game_reads_pull_only_what_they_read(cloud, aws, route):
    """A fresh Lambda instance pulled the whole game for /review/queue (~17 s on the TV),
    and hype, rallies, condensed, score, commentary and the exports did the same (D-86)."""
    gid, _ = _full_game(cloud, aws)
    r = cloud.get(f"/games/{gid}{route}")
    # 503: hype or rallies computed live need replay_render, which Lambda does not have;
    # 404: this game has no storyboard
    assert r.status_code in (200, 404, 503), r.text
    assert r.status_code != 404 or route == "/storyboard", r.text
    assert _pulled_junk(cloud, gid) == []
    if route == "/review/queue":
        assert [q["kind"] for q in r.json()["questions"]][:1] == ["shot_outcome"]
    if route == "/exports/vertical":
        assert [e["id"] for e in r.json()["exports"]] == [VID]


@pytest.mark.parametrize(
    ("method", "route", "body"),
    [
        ("PATCH", "/players/p1", {"name": "Ana"}),
        ("PATCH", "/events/e_1", {"made": True}),
        ("POST", "/events", {"t": 3.0}),
        ("POST", "/score", {"t": 3.0, "scores": [2, 0]}),
        ("GET", "/exports/vertical/" + VID, None),
    ],
)
def test_game_writes_pull_only_what_they_change(cloud, aws, method, route, body):
    gid, _ = _full_game(cloud, aws)
    r = cloud.request(method, f"/games/{gid}{route}", json=body)
    assert r.status_code < 300, r.text
    assert _pulled_junk(cloud, gid) == []
    if route == "/players/p1":  # the name save reached S3 (edits.json + game.json)
        edits = aws.get_object(Bucket=BUCKET, Key=f"games/{gid}/edits.json")["Body"].read()
        assert b"Ana" in edits
        assert cloud.get(f"/games/{gid}").json()["players"][0]["name"] == "Ana"


def test_a_pulled_folder_covers_its_files(cloud, aws):
    """Commentary asks for every play's audio file: one LIST for the folder, not one each."""
    gid, _ = _full_game(cloud, aws)
    st = cloud.app.state.storage
    from replay_api import cloud as cloud_mod

    calls = []
    real = st.listing
    st.listing = lambda g, rel="": calls.append(rel) or real(g, rel)
    token = cloud_mod.begin()
    try:
        st.game_dir_with(gid, "moments")
        for i in range(10):
            assert st.path(gid, f"moments/x_{i}.jpg").is_file()
    finally:
        cloud_mod.reset(token)
    assert calls == ["moments"]


def test_worker_claim_is_exclusive(cloud, aws):
    gid = _game(cloud)["id"]
    job = cloud.app.state.jobs.submit("process", gid, None)
    w = TestClient(cloud.app, headers={"X-Replay-Worker-Key": WORKER})
    assert (
        TestClient(cloud.app, headers={"X-Replay-Key": KEY}).post("/worker/claim").status_code
        == 401
    )
    first = w.post("/worker/claim")
    assert first.status_code == 200 and first.json()["job"]["id"] == job["id"]
    assert first.json()["job"]["status"] == "running"
    assert {f["path"] for f in first.json()["files"]} == {"game.json"}
    # a stale queue marker (the claimer died before deleting it) is still not claimable
    aws.put_object(Bucket=BUCKET, Key=f"jobs/queue/{time.time_ns():020d}-{job['id']}", Body=b"")
    assert w.post("/worker/claim").status_code == 204


def test_upload_urls_reject_traversal_and_finish(cloud):
    gid = _game(cloud)["id"]
    job = cloud.app.state.jobs.submit("process", gid, None)
    w = TestClient(cloud.app, headers={"X-Replay-Worker-Key": WORKER})
    base = f"/worker/jobs/{job['id']}"
    assert w.post(f"{base}/progress", json={"stage": "detect", "fraction": 0.5}).status_code == 409
    w.post("/worker/claim")
    for bad in ("../x", "/etc/passwd", "a/../../b", "..", "a\\..\\b", ""):
        assert w.post(f"{base}/upload-urls", json={"paths": [bad]}).status_code == 400, bad
    urls = w.post(f"{base}/upload-urls", json={"paths": ["media/wide.mp4"]}).json()
    assert f"games/{gid}/media/wide.mp4" in urls["media/wide.mp4"]
    p = w.post(f"{base}/progress", json={"stage": "detect", "fraction": 0.5, "status": "done"})
    assert p.json()["status"] == "running" and p.json()["fraction"] == 0.5
    assert cloud.get(f"/games/{gid}").json()["status"] == "processing"
    done = w.post(f"{base}/finish", json={"ok": False, "error": "boom"}).json()
    assert done["status"] == "failed" and done["error"] == "boom"
    assert w.post(f"{base}/finish", json={"ok": True}).status_code == 409


def test_cloud_gaps_answer_cleanly(cloud):
    assert cloud.post("/sessions").status_code == 501
    gid = _game(cloud)["id"]
    with pytest.raises(Exception, match="cloud mode"):
        cloud.app.state.jobs.submit("render", gid, None)  # jobs the runner does not run
    r = cloud.post("/profiles", json={"name": "Ana"})
    assert r.status_code == 201
    pid = r.json()["profile_id"]
    assert cloud.app.state.storage.s3.head_object(Bucket=BUCKET, Key="profiles/profiles.sqlite")
    r = cloud.post(f"/profiles/{pid}/face", data={"consent": "true"},
                   files={"photos": ("a.jpg", b"x", "image/jpeg")})  # fmt: skip
    assert r.status_code == 503


def test_secrets_come_from_ssm(cloud_settings, aws):
    ssm = boto3.client("ssm")
    for name, value in (("api-key", "from-ssm"), ("worker-key", "w"), ("upload-token-secret", "s")):
        ssm.put_parameter(Name=f"/replay/{name}", Value=value, Type="SecureString")
    s = dataclasses.replace(cloud_settings, ssm_prefix="/replay/", api_key=None, worker_key=None,
                            upload_token_secret=None)  # fmt: skip
    with TestClient(create_app(s)) as c:
        assert c.get("/games", headers={"X-Replay-Key": KEY}).status_code == 401
        assert c.get("/games", headers={"X-Replay-Key": "from-ssm"}).status_code == 200


def test_remote_runner_end_to_end(cloud, cloud_settings, tmp_path, aws, caplog):
    """Phone upload -> calibrate -> process (queued in S3) -> runner on a separate mirror
    -> files back in S3 -> the API serves a ready game; then an autocalib job. The log
    never holds a presigned query (security token)."""
    from replay_api import remote_runner as rr

    rr.quiet_http_logs()
    caplog.set_level(logging.DEBUG)

    gid = _game(cloud)["id"]
    _upload(cloud, gid)
    assert cloud.post(f"/games/{gid}/calibration", json=CALIB).status_code == 200
    r = cloud.post(f"/games/{gid}/process")
    assert r.status_code == 202, r.text
    assert cloud.get(f"/games/{gid}").json()["status"] == "processing"

    runner_settings = dataclasses.replace(
        cloud_settings, storage="local", jobs="local", data_dir=tmp_path / "runner"
    )
    worker = TestClient(cloud.app)
    with httpx.Client() as http:
        api = rr.Api(worker, WORKER, http, tries=2, backoff_s=0.01)
        assert rr.run_once(api, runner_settings) is True
        assert rr.run_once(api, runner_settings) is False  # queue drained

        game = cloud.get(f"/games/{gid}").json()
        assert game["status"] == "ready", game
        assert set(game["stages"].values()) == {"done"}
        keys = {
            o["Key"] for o in aws.list_objects_v2(Bucket=BUCKET, Prefix=f"games/{gid}/")["Contents"]
        }
        assert {
            f"games/{gid}/{k}" for k in ("media/wide.mp4", "events.json", "tracks/00000.json")
        } <= keys
        assert cloud.get(f"/games/{gid}/stats").status_code == 200
        jobs = cloud.get(f"/games/{gid}/jobs").json()
        assert [j["status"] for j in jobs] == ["done"]

        r = cloud.post(f"/games/{gid}/calibration/auto",
                       json={"sport": "basketball", "variant": "half"})  # fmt: skip
        assert r.status_code == 202, r.text
        assert cloud.get(f"/games/{gid}/calibration/auto").json()["status"] == "queued"
        assert rr.run_once(api, runner_settings) is True
        auto = cloud.get(f"/games/{gid}/calibration/auto").json()
        assert auto["status"] == "done" and auto["ok"], auto
    # what runner.log gets: the runner's own lines and the HTTP clients' (the in-process
    # API's botocore/moto lines are not the runner's)
    logged = [r.getMessage() for r in caplog.records if r.name == "replay_api.remote_runner"
              or r.name.split(".")[0] in ("httpx", "httpcore")]  # fmt: skip
    assert any(m.startswith("GET /") and f"games/{gid}/" in m for m in logged)  # mirror
    assert any(m.startswith("PUT /") and m.endswith(f"games/{gid}/events.json") for m in logged)
    assert not any("X-Amz" in m or "Signature" in m or "?" in m for m in logged)


def test_runner_errors_redact_presigned_urls():
    from replay_api import remote_runner as rr

    url = "https://b.s3.amazonaws.com/games/g_1/x.mp4?X-Amz-Security-Token=SECRET&X-Amz-Signature=s"
    r = httpx.Response(403, request=httpx.Request("PUT", url))
    with pytest.raises(httpx.HTTPStatusError) as exc:
        rr._checked(r)
    assert str(exc.value) == "HTTP 403 for PUT /games/g_1/x.mp4"


def test_phone_token_in_cloud_mode(cloud, aws):
    """The phone-link token opens its game's tag/clip routes on Lambda + S3 (profiles in
    the S3-mirrored SQLite), and no upload route."""
    a, b = _game(cloud), _game(cloud)
    gid = a["id"]
    _upload(cloud, gid)
    link = cloud.post(f"/games/{gid}/phone-link", json={"job": "tag", "t": 4}).json()
    assert link["url"] == f"https://replay.example/p/{gid}?job=tag&t=4#k={link['token']}"
    assert TestClient(cloud.app).get("/config").json() == {"web_base": "https://replay.example"}
    anon = TestClient(cloud.app, headers={"X-Replay-Phone-Token": link["token"]})
    assert anon.get(f"/games/{gid}").json()["id"] == gid
    assert anon.get(f"/games/{gid}/clips").status_code == 200
    prof = anon.post("/profiles", json={"name": "Riley"})
    assert prof.status_code == 201, prof.text
    pid = prof.json()["profile_id"]
    assert any(p["profile_id"] == pid for p in anon.get("/profiles").json()["profiles"])
    assert anon.post(f"/profiles/{pid}/links",
                     json={"game_id": b["id"], "player_id": "p1"}).status_code == 403  # fmt: skip
    assert anon.get(f"/games/{b['id']}").status_code == 401
    for path in ("upload/multipart", "upload/complete", "calibration", "process"):
        assert anon.post(f"/games/{gid}/{path}", json={}).status_code == 401, path
    # and the upload token does not open the phone routes
    up = TestClient(cloud.app, headers={"X-Replay-Upload-Token": a["upload_token"]})
    assert up.get(f"/games/{gid}/clips").status_code == 401
    assert up.get("/profiles").status_code == 401


def test_list_parts_resumes_a_dropped_upload(cloud, aws):
    """The phone lost its connection after part 1: list-parts names what S3 holds and
    hands out URLs for the rest; the upload completes from there. Token-auth, own game."""
    a, b = _game(cloud), _game(cloud)
    gid = a["id"]
    phone = TestClient(cloud.app, headers={"X-Replay-Upload-Token": a["upload_token"]})
    data = TINY_MP4.read_bytes() + b"\0" * ((33 << 20) - TINY_MP4.stat().st_size)  # 3 parts
    init = phone.post(f"/games/{gid}/upload/multipart", json={"size": len(data)}).json()
    size, uid = init["part_size"], init["upload_id"]
    assert [p["n"] for p in init["parts"]] == [1, 2, 3]
    first = httpx.put(init["parts"][0]["url"], content=data[:size])
    httpx.put(init["parts"][1]["url"], content=data[size : size + 1000])  # cut short

    q = {"upload_id": uid, "size": len(data)}
    got = phone.get(f"/games/{gid}/upload/parts", params=q).json()
    assert got["part_size"] == size and got["upload_id"] == uid
    assert got["done"] == [{"n": 1, "etag": first.headers["etag"], "size": size}]
    assert [p["n"] for p in got["parts"]] == [2, 3]  # the short part 2 goes again
    parts = [{"n": 1, "etag": first.headers["etag"]}]
    for p in got["parts"]:
        chunk = data[(p["n"] - 1) * size : p["n"] * size]
        parts.append({"n": p["n"], "etag": httpx.put(p["url"], content=chunk).headers["etag"]})
    r = phone.post(f"/games/{gid}/upload/complete", json={"upload_id": uid, "parts": parts})
    assert r.status_code == 200 and r.json()["status"] == "uploaded"
    assert 19.5 < r.json()["video"]["duration_s"] < 20.5  # probed at upload, for the ETA
    got = aws.get_object(Bucket=BUCKET, Key=f"games/{gid}/source.mp4")["Body"].read()
    assert got == data

    # gone once completed; another game's token or id never reaches it
    assert phone.get(f"/games/{gid}/upload/parts", params=q).status_code == 404
    other = {"X-Replay-Upload-Token": b["upload_token"]}
    assert TestClient(cloud.app).get(f"/games/{gid}/upload/parts", params=q,
                                     headers=other).status_code == 401  # fmt: skip
    up_b = cloud.post(f"/games/{b['id']}/upload/multipart", json={"size": 10}).json()
    assert phone.get(f"/games/{gid}/upload/parts",
                     params={"upload_id": up_b["upload_id"], "size": 10}).status_code == 404  # fmt: skip
    assert (
        cloud.get(f"/games/{gid}/upload/parts", params={"upload_id": "x", "size": 0}).status_code
        == 422
    )


def test_remote_runner_tv_fields_and_early_push(cloud, cloud_settings, tmp_path, aws, monkeypatch):
    """The runner pushes media/ and storyboard/ while the job runs (so the TV can play a
    processing game), and the API serves hero, storyboard, moments and readiness from S3."""
    from replay_api import remote_runner as rr

    gid = _game(cloud)["id"]
    _upload(cloud, gid)
    assert cloud.post(f"/games/{gid}/calibration", json=CALIB).status_code == 200
    game = cloud.post(f"/games/{gid}/process")
    queued = cloud.get(f"/games/{gid}").json()
    assert queued["watchable"] is False and queued["stage_label"] == "Waiting to start"
    assert queued["eta_s"] >= 30  # at least one runner poll
    assert queued["features"]["moments"]["state"] == "pending"

    early: list[tuple] = []
    real_push = rr.push

    def spy(api, job_id, root, before, only=None):
        n = real_push(api, job_id, root, before, only)
        if only:
            early.append((n, set(aws_keys())))
        return n

    def aws_keys():
        objs = aws.list_objects_v2(Bucket=BUCKET, Prefix=f"games/{gid}/").get("Contents", [])
        return {o["Key"].split("/", 2)[2] for o in objs}

    monkeypatch.setattr(rr, "push", spy)
    runner = dataclasses.replace(cloud_settings, storage="local", jobs="local",
                                 data_dir=tmp_path / "runner")  # fmt: skip
    with httpx.Client() as http:
        api = rr.Api(TestClient(cloud.app), WORKER, http, tries=2, backoff_s=0.01)
        assert rr.run_once(api, runner) is True
    # the first early push (after ingest) put the mezzanine up before the run ended
    assert early and early[0][0] >= 1 and "media/wide.mp4" in early[0][1]
    assert "events.json" not in early[0][1]  # everything else waits for the final push

    game = cloud.get(f"/games/{gid}").json()
    assert game["status"] == "ready" and game["watchable"] is True
    assert game["features"]["moments"] == {"state": "ready"}
    hero = TestClient(cloud.app).get(game["hero_url"], follow_redirects=False)
    assert (
        hero.status_code == 302 and httpx.get(hero.headers["location"]).content[:2] == b"\xff\xd8"
    )
    sb = cloud.get(game["storyboard_url"]).json()
    assert sb["count"] == 10 and f"/media/games/{gid}/storyboard/0000.jpg?v=" in sb["sheets"][0]
    ms = cloud.get(f"/games/{gid}/moments").json()
    assert [m["label"] for m in ms if m["kind"] == "score"] == ["Basket, Marcus", "Basket, Alex"]
    assert all(m["thumb_url"] for m in ms)
    phone = {"X-Replay-Upload-Token": _token(cloud, gid)}
    assert TestClient(cloud.app).get(f"/games/{gid}/moments", headers=phone).status_code == 401


def test_remote_runner_renders_the_highlight_reel(cloud, cloud_settings, tmp_path, aws,
                                                  monkeypatch):  # fmt: skip
    """The phone asks for the reel (phone token); the job waits in S3 for the runner,
    which runs the worker's `reel` stage and uploads it; the API then serves its URL."""
    pytest.importorskip("replay_render")
    pytest.importorskip("replay_worker")
    import shutil

    if shutil.which("ffmpeg") is None:
        pytest.skip("needs ffmpeg")
    from replay_api import remote_runner as rr

    monkeypatch.setenv("REPLAY_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("REPLAY_GPU_LOCK", str(tmp_path / "gpu.lock"))
    gid = _game(cloud)["id"]
    _upload(cloud, gid)
    assert cloud.post(f"/games/{gid}/calibration", json=CALIB).status_code == 200
    cloud.post(f"/games/{gid}/process")
    runner = dataclasses.replace(cloud_settings, storage="local", jobs="local",
                                 data_dir=tmp_path / "runner")  # fmt: skip
    link = cloud.post(f"/games/{gid}/phone-link", json={"job": "reel"}).json()
    assert f"/p/{gid}?job=reel#k=" in link["url"]
    phone = TestClient(cloud.app, headers={"X-Replay-Phone-Token": link["token"]})
    with httpx.Client() as http:
        api = rr.Api(TestClient(cloud.app), WORKER, http, tries=2, backoff_s=0.01)
        assert rr.run_once(api, runner) is True  # the processing job
        r = phone.post(f"/games/{gid}/exports/reel", json={"aspect": "16:9"})
        assert r.status_code == 202, r.text
        rid, job_id = r.json()["id"], r.json()["job_id"]
        assert phone.get(f"/games/{gid}/exports/reel/{rid}").json()["status"] == "queued"
        assert cloud.app.state.jobs.get(job_id)["params"] == {"stage": "reel"}
        assert rr.run_once(api, runner) is True  # the reel job
    got = phone.get(f"/games/{gid}/exports/reel/{rid}").json()
    assert got["status"] == "done" and got["segments"], got
    assert f"/exports/reel/{rid}.mp4" in got["url"]
    media = TestClient(cloud.app).get(got["url"], follow_redirects=False)
    head = httpx.get(media.headers["location"], headers={"Range": "bytes=4-7"})
    assert head.status_code == 206 and head.content == b"ftyp"
    assert phone.post(f"/games/{gid}/exports/reel", json={}).json()["status"] == "done"
    assert cloud.app.state.jobs.get(job_id)["status"] == "done"


def _token(cloud, gid: str) -> str:
    return auth.make_token(SECRET, gid)
