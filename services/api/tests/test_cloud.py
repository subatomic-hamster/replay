"""D-80 cloud mode against a fake S3/SSM (moto's server, so presigned URLs are real HTTP):
upload tokens, multipart upload, media redirects, the /worker API and the remote runner."""

from __future__ import annotations

import base64
import dataclasses
import json
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


def test_remote_runner_end_to_end(cloud, cloud_settings, tmp_path, aws):
    """Phone upload -> calibrate -> process (queued in S3) -> runner on a separate mirror
    -> files back in S3 -> the API serves a ready game; then an autocalib job."""
    from replay_api import remote_runner as rr

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
