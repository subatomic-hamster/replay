"""Phone pages (clip, tag, review, search): GET /config, POST /games/{id}/phone-link and
the phone token's allowlist (auth.PHONE_ROUTES), kept apart from the upload token."""

from __future__ import annotations

import base64
import dataclasses
import time
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from replay_api import auth
from replay_api.main import create_app

from .conftest import ready_game

KEY, SECRET = "s3cret", "t0ken-secret"


@pytest.fixture
def phone_settings(settings):
    return dataclasses.replace(settings, api_key=KEY, upload_token_secret=SECRET,
                               public_web_base="https://replay.example/")  # fmt: skip


@pytest.fixture
def tv(phone_settings):
    with TestClient(create_app(phone_settings), headers={"X-Replay-Key": KEY}) as c:
        yield c


@pytest.fixture
def anon(tv):
    return TestClient(tv.app)


def _link(tv, gid, job="clip", t=None) -> dict:
    r = tv.post(f"/games/{gid}/phone-link", json={"job": job, "t": t})
    assert r.status_code == 200, r.text
    return r.json()


def _ph(token: str) -> dict:
    return {"X-Replay-Phone-Token": token}


# ------------------------------------------------------------------ /config


def test_config_is_public(tv, anon, settings):
    assert anon.get("/config").json() == {"web_base": "https://replay.example"}
    with TestClient(create_app(settings)) as c:  # REPLAY_PUBLIC_WEB_BASE unset
        assert c.get("/config").json() == {"web_base": None}


# ------------------------------------------------------------------ phone-link


def test_phone_link_shape(tv, anon, phone_settings):
    gid = ready_game(tv, phone_settings)
    out = _link(tv, gid, "clip", 12.5)
    assert out["url"] == f"https://replay.example/p/{gid}?job=clip&t=12.5#k={out['token']}"
    assert abs(out["expires_at"] - (time.time() + auth.TTL_S)) < 5
    assert auth.token_game(SECRET, out["token"], kind=auth.PHONE) == gid
    parts = urlsplit(_link(tv, gid, "review")["url"])
    assert parse_qs(parts.query) == {"job": ["review"]} and parts.fragment.startswith("k=")
    assert "&t=30#" in _link(tv, gid, "tag", 30)["url"]
    # key required; unknown game; bad job / t
    assert anon.post(f"/games/{gid}/phone-link", json={"job": "clip"}).status_code == 401
    assert anon.post(f"/games/{gid}/phone-link", json={"job": "clip"},
                     headers=_ph(out["token"])).status_code == 401  # fmt: skip
    assert tv.post("/games/g_00ff/phone-link", json={"job": "clip"}).status_code == 404
    assert tv.post(f"/games/{gid}/phone-link", json={"job": "upload"}).status_code == 422
    assert tv.post(f"/games/{gid}/phone-link", json={"job": "clip", "t": -1}).status_code == 422


def test_phone_link_without_web_base(settings):
    s = dataclasses.replace(settings, api_key=KEY, upload_token_secret=SECRET)
    with TestClient(create_app(s), headers={"X-Replay-Key": KEY}) as tv:
        gid = ready_game(tv, s)
        out = _link(tv, gid, "search")
        assert out["url"] is None and auth.token_game(SECRET, out["token"], kind=auth.PHONE)


# ------------------------------------------------------------------ token kinds


def test_token_kinds_never_interchange():
    up = auth.make_token(SECRET, "g_ab12")
    ph = auth.make_token(SECRET, "g_ab12", kind=auth.PHONE)
    assert auth.token_game(SECRET, up) == "g_ab12"
    assert auth.token_game(SECRET, ph, kind=auth.PHONE) == "g_ab12"
    assert auth.token_game(SECRET, ph) is None
    assert auth.token_game(SECRET, up, kind=auth.PHONE) is None
    assert auth.phone_allows(SECRET, up, "GET", "/games/g_ab12/clips") is None
    assert not auth.token_allows(SECRET, ph, "POST", "/games/g_ab12/upload/multipart")
    assert not auth.token_allows(SECRET, ph, "GET", "/games/g_ab12")


def _tamper(token: str) -> str:
    raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode()
    head, exp, mac = raw.rsplit(".", 2)
    forged = f"{head}.{int(exp) + 86400}.{mac}".encode()
    return base64.urlsafe_b64encode(forged).decode().rstrip("=")


# ------------------------------------------------------------------ allowlist


def _concrete(path: str, gid: str, pid: str) -> str:
    return (
        path.replace("/profiles/{id}", f"/profiles/{pid}").replace("{g}", gid).replace("{id}", "x1")
    )


BODIES = {
    "/profiles": {"name": "Sam"},
    "/profiles/{id}/links": {"game_id": "{g}", "player_id": "p1"},
    "/games/{g}/triggers": {"t": 1.0},
    "/games/{g}/clips/{id}": {"t_start": 0, "t_end": 1},
    "/games/{g}/exports/vertical": {"t_start": -1},  # 422: past auth, no render job
    "/games/{g}/players/{id}": {"name": "Sam"},
    "/games/{g}/events/{id}": {"confirmed": True},
    "/games/{g}/search": {"text": "threes"},
    "/games/{g}/query": {"text": "threes"},
}


def test_every_allowed_route_opens(tv, anon, phone_settings):
    gid = ready_game(tv, phone_settings)
    pid = tv.post("/profiles", json={"name": "Alex"}).json()["profile_id"]
    phone = _ph(_link(tv, gid)["token"])
    upload = {"X-Replay-Upload-Token": auth.make_token(SECRET, gid)}
    for method, path in auth.PHONE_ROUTES:
        url = _concrete(path, gid, pid)
        body = BODIES.get(path)
        if body and "game_id" in body:
            body = {**body, "game_id": gid}
        kw = {"json": body} if method in ("POST", "PATCH") else {}
        r = anon.request(method, url, headers=phone, **kw)
        assert r.status_code not in (401, 403), (method, url, r.status_code, r.text)
        assert anon.request(method, url, **kw).status_code == 401, (method, url)
        if path not in ("/games/{g}", "/sports"):  # the upload page shares just these two
            assert anon.request(method, url, headers=upload, **kw).status_code == 401, url


def test_forbidden_routes(tv, anon, phone_settings):
    a, b = ready_game(tv, phone_settings), ready_game(tv, phone_settings, "Other")
    pid = tv.post("/profiles", json={"name": "Alex"}).json()["profile_id"]
    tok = _link(tv, a)["token"]
    ph = _ph(tok)
    denied = [
        ("GET", "/games"),
        ("GET", f"/games/{b}"),
        ("GET", f"/games/{b}/clips"),
        ("PATCH", f"/games/{b}/players/p1"),
        ("PUT", f"/games/{a}/upload"),
        ("POST", f"/games/{a}/upload/multipart"),
        ("POST", f"/games/{a}/upload/complete"),
        ("GET", f"/games/{a}/upload/parts"),
        ("GET", f"/games/{a}/jobs"),
        ("POST", f"/games/{a}/calibration"),
        ("POST", f"/games/{a}/calibration/auto"),
        ("POST", f"/games/{a}/process"),
        ("POST", f"/games/{a}/phone-link"),
        ("POST", f"/games/{a}/events"),
        ("POST", f"/games/{a}/faces/match"),
        ("POST", f"/games/{a}/players/p1/render"),
        ("GET", f"/profiles/{pid}"),
        ("PATCH", f"/profiles/{pid}"),
        ("DELETE", f"/profiles/{pid}"),
        ("PUT", f"/profiles/{pid}/photo"),
        ("POST", f"/profiles/{pid}/face"),
        ("POST", f"/profiles/{pid}/card"),
        ("DELETE", f"/profiles/{pid}/links/{b}/p1"),
        ("POST", "/worker/claim"),
        ("POST", "/sessions"),
    ]
    for method, url in denied:
        assert anon.request(method, url, headers=ph).status_code == 401, (method, url)
    # the link route checks the body's game; a phone profile takes no photo URL
    r = anon.post(f"/profiles/{pid}/links", json={"game_id": b, "player_id": "p1"}, headers=ph)
    assert r.status_code == 403
    r = anon.post("/profiles", json={"name": "S", "photo_url": "https://x/y.jpg"}, headers=ph)
    assert r.status_code == 403
    # expired, tampered, other secret, an upload token in the phone header
    old = auth.make_token(SECRET, a, now=time.time() - auth.TTL_S - 5, kind=auth.PHONE)
    for bad in (old, _tamper(tok), auth.make_token("nope", a, kind=auth.PHONE),
                auth.make_token(SECRET, a), "garbage!"):  # fmt: skip
        assert anon.get(f"/games/{a}/clips", headers=_ph(bad)).status_code == 401, bad


def test_phone_tags_and_trims_its_game(tv, anon, phone_settings):
    gid = ready_game(tv, phone_settings)
    ph = _ph(_link(tv, gid, "tag")["token"])
    prof = anon.post("/profiles", json={"name": "Jordan"}, headers=ph)
    assert prof.status_code == 201, prof.text
    r = anon.post(f"/profiles/{prof.json()['profile_id']}/links", json={"game_id": gid, "player_id": "p1"},
                  headers=ph)  # fmt: skip
    assert r.status_code == 200, r.text
    players = anon.get(f"/games/{gid}", headers=ph).json()["players"]
    assert next(p for p in players if p["id"] == "p1")["name"] == "Jordan"
    assert anon.get("/profiles", headers=ph).status_code == 200
