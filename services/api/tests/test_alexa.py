"""docs/alexa.md: POST /alexa request verification (a self-made CA stands in for Amazon's,
the cert fetch is monkeypatched) and the TV relay (/tv/pair, /tv/state, /tv/commands)."""

from __future__ import annotations

import base64
import dataclasses
import datetime
import json
import time

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from fastapi.testclient import TestClient
from replay_api import alexa_routes, alexa_verify, discovery_routes
from replay_api.main import create_app

from .conftest import new_game
from .test_cloud import BUCKET, KEY, aws, cloud_settings, moto_url  # noqa: F401 (fixtures)

SKILL = "amzn1.ask.skill.test-0000"
USER = "amzn1.ask.account.TESTUSER"
CERT_URL = "https://s3.amazonaws.com/echo.api/echo-api-cert-99.pem"
UTC = datetime.UTC


def _name(cn: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])


def _cert(subject, issuer, key, signer, *, ca: bool, san: str | None = None,
          days=(-1, 30), path_len=None):  # fmt: skip
    now = datetime.datetime.now(UTC)
    b = (
        x509.CertificateBuilder().subject_name(_name(subject)).issuer_name(_name(issuer))
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now + datetime.timedelta(days=days[0]))
        .not_valid_after(now + datetime.timedelta(days=days[1]))
        .add_extension(x509.BasicConstraints(ca=ca, path_length=path_len), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(signer.public_key()),
                       False)
    )  # fmt: skip
    if ca:
        b = b.add_extension(x509.KeyUsage(False, False, False, False, False, True, True,
                                          False, False), critical=True)  # fmt: skip
    else:
        b = b.add_extension(x509.KeyUsage(True, False, True, False, False, False, False,
                                          False, False), critical=True)  # fmt: skip
        b = b.add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), False)
        b = b.add_extension(x509.SubjectAlternativeName([x509.DNSName(san)]), False)
    return b.sign(signer, hashes.SHA256())


@pytest.fixture(scope="module")
def pki():
    keys = [rsa.generate_private_key(public_exponent=65537, key_size=2048) for _ in range(3)]
    root_k, mid_k, leaf_k = keys
    root = _cert("Test Root", "Test Root", root_k, root_k, ca=True)
    mid = _cert("Test Mid", "Test Root", mid_k, root_k, ca=True, path_len=0)
    leaf = _cert("echo-api.amazon.com", "Test Mid", leaf_k, mid_k, ca=False,
                 san="echo-api.amazon.com")  # fmt: skip
    other = _cert("evil.example", "Test Mid", leaf_k, mid_k, ca=False, san="evil.example")
    expired = _cert("echo-api.amazon.com", "Test Mid", leaf_k, mid_k, ca=False,
                    san="echo-api.amazon.com", days=(-30, -1))  # fmt: skip
    return {"root": root, "chain": (leaf, mid), "key": leaf_k, "other": (other, mid),
            "expired": (expired, mid)}  # fmt: skip


@pytest.fixture
def chain(pki, monkeypatch):
    """The cert URL serves `chain["served"]` (the good chain unless a test swaps it)."""
    box = {"served": pki["chain"], "fetched": []}

    def fetch(url):
        box["fetched"].append(url)
        return box["served"]

    monkeypatch.setattr(alexa_verify, "fetch_chain", fetch)
    monkeypatch.setattr(alexa_verify, "trust_store", lambda: alexa_verify.Store([pki["root"]]))
    return box


@pytest.fixture
def app_client(settings, chain, monkeypatch):
    queued = []

    def fake_submit(request, game_id, kind, stage):  # no render in tests
        queued.append((game_id, kind, stage))
        return {"id": "j_fake", "status": "queued"}

    monkeypatch.setattr(discovery_routes, "_submit", fake_submit)
    s = dataclasses.replace(settings, alexa_skill_id=SKILL)
    with TestClient(create_app(s)) as c:
        c.queued = queued  # type: ignore[attr-defined]
        yield c


def _envelope(request: dict, *, skill=SKILL, user=USER, ts=None) -> dict:
    ts = ts or datetime.datetime.now(UTC)
    return {
        "version": "1.0",
        "session": {"new": True, "sessionId": "s1", "application": {"applicationId": skill},
                    "user": {"userId": user}},
        "context": {"System": {"application": {"applicationId": skill},
                               "user": {"userId": user}, "device": {"deviceId": "d1"}}},
        "request": {"requestId": "r1", "locale": "en-US",
                    "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%SZ"), **request},
    }  # fmt: skip


def _intent(name: str, **slots) -> dict:
    return {"type": "IntentRequest", "intent": {
        "name": name, "slots": {k: {"name": k, "value": v} for k, v in slots.items()}}}  # fmt: skip


def _post(client, env: dict, key=None, url=CERT_URL, tamper=False):
    body = json.dumps(env).encode()
    sig = (key or client.pki_key).sign(body, padding.PKCS1v15(), hashes.SHA256())
    if tamper:
        body = body.replace(b'"requestId": "r1"', b'"requestId": "r2"')
        assert b'"r2"' in body
    return client.post("/alexa", content=body, headers={
        "SignatureCertChainUrl": url, "Signature-256": base64.b64encode(sig).decode(),
        "Content-Type": "application/json"})  # fmt: skip


@pytest.fixture
def alexa(app_client, pki):
    app_client.pki_key = pki["key"]  # type: ignore[attr-defined]
    return app_client


def _speech(r) -> str:
    assert r.status_code == 200, r.text
    return r.json()["response"]["outputSpeech"]["text"]


# --------------------------------------------------------------------------- verification


def test_valid_request_is_answered(alexa, chain):
    r = _post(alexa, _envelope({"type": "LaunchRequest"}))
    assert "isn't paired" in _speech(r)
    assert chain["fetched"] == [CERT_URL]


def test_bad_signature_is_400(alexa, pki):
    env = _envelope({"type": "LaunchRequest"})
    assert _post(alexa, env, tamper=True).status_code == 400
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    assert _post(alexa, env, key=other_key).status_code == 400
    body = json.dumps(env).encode()
    bad = alexa.post("/alexa", content=body, headers={"SignatureCertChainUrl": CERT_URL,
                                                      "Signature-256": "%%%"})  # fmt: skip
    assert bad.status_code == 400
    assert alexa.post("/alexa", content=body).status_code == 400  # no headers at all


def test_stale_timestamp_is_400(alexa):
    old = datetime.datetime.now(UTC) - datetime.timedelta(seconds=200)
    assert _post(alexa, _envelope({"type": "LaunchRequest"}, ts=old)).status_code == 400
    ok = datetime.datetime.now(UTC) - datetime.timedelta(seconds=100)
    assert _post(alexa, _envelope({"type": "LaunchRequest"}, ts=ok)).status_code == 200


def test_wrong_skill_id_is_400(alexa, settings, chain, pki):
    assert _post(alexa, _envelope({"type": "LaunchRequest"}, skill="amzn1.ask.skill.other")
                 ).status_code == 400  # fmt: skip
    # no skill id configured at all: nothing is accepted
    with TestClient(create_app(settings)) as bare:
        bare.pki_key = pki["key"]  # type: ignore[attr-defined]
        assert _post(bare, _envelope({"type": "LaunchRequest"})).status_code == 400


@pytest.mark.parametrize("url", [
    "http://s3.amazonaws.com/echo.api/echo-api-cert.pem",
    "https://notamazon.com/echo.api/echo-api-cert.pem",
    "https://s3.amazonaws.com/EcHo.aPi/echo-api-cert.pem",
    "https://s3.amazonaws.com/invalid.path/echo-api-cert.pem",
    "https://s3.amazonaws.com:563/echo.api/echo-api-cert.pem",
    "https://s3.amazonaws.com/echo.api/../evil/cert.pem",
    "https://s3.amazonaws.com@evil.example/echo.api/cert.pem",
    "https://s3.amazonaws.com:99999/echo.api/cert.pem",
    "",
])  # fmt: skip
def test_bad_cert_url_is_400_without_fetching(alexa, chain, url):
    assert _post(alexa, _envelope({"type": "LaunchRequest"}), url=url).status_code == 400
    assert chain["fetched"] == []


@pytest.mark.parametrize("url", [
    "https://s3.amazonaws.com/echo.api/echo-api-cert.pem",
    "HTTPS://s3.AmazonAWS.com:443/echo.api/echo-api-cert.pem",
    "https://s3.amazonaws.com/echo.api/../echo.api/echo-api-cert.pem",
])  # fmt: skip
def test_amazons_valid_cert_urls(url):
    alexa_verify.check_cert_url(url)


def test_cert_must_name_echo_api_and_be_in_date(alexa, chain, pki):
    env = _envelope({"type": "LaunchRequest"})
    chain["served"] = pki["other"]  # SAN evil.example
    assert _post(alexa, env).status_code == 400
    chain["served"] = pki["expired"]
    assert _post(alexa, env).status_code == 400
    chain["served"] = pki["chain"][:1]  # no intermediate: no path to the root
    assert _post(alexa, env).status_code == 400
    chain["served"] = ()
    assert _post(alexa, env).status_code == 400


def test_alexa_needs_no_api_key_but_tv_routes_do(settings, chain, pki):
    s = dataclasses.replace(settings, api_key="k3y", alexa_skill_id=SKILL)
    with TestClient(create_app(s)) as c:
        c.pki_key = pki["key"]  # type: ignore[attr-defined]
        assert _post(c, _envelope({"type": "LaunchRequest"})).status_code == 200
        for method, path in (("post", "/tv/pair"), ("post", "/tv/state"),
                             ("get", "/tv/commands"), ("post", "/tv/commands/x/ack")):  # fmt: skip
            assert getattr(c, method)(path).status_code == 401, path
        assert c.post("/tv/pair", headers={"X-Replay-Key": "k3y"}).status_code == 200


# --------------------------------------------------------------------------- the relay


def _pair(alexa) -> str:
    code = alexa.post("/tv/pair").json()["code"]
    assert "Paired" in _speech(_post(alexa, _envelope(_intent("PairIntent", code=code))))
    return code


def test_pair_then_commands_reach_the_tv(alexa):
    gid = new_game(alexa)
    # before pairing: honest refusals
    assert "isn't paired" in _speech(_post(alexa, _envelope(_intent("ClipThatIntent"))))
    assert alexa.get("/tv/commands").json() == {"commands": [], "cursor": "", "paired": False}

    tv = alexa.post("/tv/pair").json()
    assert len(tv["code"]) == 4 and tv["code"].isdigit() and tv["paired"] is False
    assert tv["expires_at"] > time.time() + 200
    wrong = str((int(tv["code"]) - 1000 + 1) % 9000 + 1000)
    assert "doesn't match" in _speech(_post(alexa, _envelope(_intent("PairIntent", code=wrong))))
    said = _speech(_post(alexa, _envelope(_intent("PairIntent", code=tv["code"]))))
    assert said.startswith("Paired")
    polled = alexa.get("/tv/commands").json()
    assert polled["paired"] is True and [c["kind"] for c in polled["commands"]] == ["paired"]
    # the code is single-use
    again = _speech(_post(alexa, _envelope(_intent("PairIntent", code=tv["code"]))))
    assert "isn't showing a pairing code" in again

    # paired, but no game open on the TV
    assert "Open a game" in _speech(_post(alexa, _envelope(_intent("ExportReelIntent"))))
    assert alexa.post("/tv/state", json={"game_id": gid, "t": 42.5}).status_code == 200
    assert "clipping" in _speech(_post(alexa, _envelope(_intent("ClipThatIntent"))))
    said = _speech(_post(alexa, _envelope(_intent("ExportReelIntent"))))
    assert "highlight reel" in said and "Scan the code" in said
    [(q_gid, q_kind, q_stage)] = alexa.queued  # the reel job, queued during the request
    assert q_gid == gid and q_kind.startswith("reel:r_") and q_stage == "reel"

    cur = polled["cursor"]
    got = alexa.get("/tv/commands", params={"after": cur}).json()
    clip, reel = got["commands"]
    assert (clip["kind"], clip["game_id"], clip["t"]) == ("clip_that", gid, 42.5)
    assert clip["source"] == "alexa" and clip["created_at"] <= time.time()
    assert reel["kind"] == "export_reel" and reel["game_id"] == gid
    assert reel["reel"]["id"].startswith("r_") and reel["reel"]["status"] == "queued"
    assert got["cursor"] == reel["id"]
    assert alexa.get("/tv/commands", params={"after": reel["id"]}).json()["commands"] == []

    # ack: never delivered again, even without a cursor
    assert alexa.post(f"/tv/commands/{clip['id']}/ack").json() == {"id": clip["id"],
                                                                   "acked": True}  # fmt: skip
    left = [c["id"] for c in alexa.get("/tv/commands").json()["commands"]]
    assert clip["id"] not in left and reel["id"] in left
    assert alexa.post("/tv/commands/../ack").status_code == 404
    assert alexa.post("/tv/commands/c_nope/ack").status_code == 404


def test_playing_tv_time_runs_on_and_stale_tv_is_not_watching(alexa):
    gid = new_game(alexa)
    _pair(alexa)
    store = alexa.app.state.alexa
    store.put("tv", {"game_id": gid, "t": 10.0, "playing": True, "at": time.time() - 4})
    _post(alexa, _envelope(_intent("ClipThatIntent")))
    clip = alexa.get("/tv/commands").json()["commands"][-1]
    assert 13.9 < clip["t"] < 15.0
    store.put("tv", {"game_id": gid, "t": 10.0, "playing": True, "at": time.time() - 31})
    assert "Open a game" in _speech(_post(alexa, _envelope(_intent("ClipThatIntent"))))
    assert alexa.post("/tv/state", json={"game_id": "../x", "t": 1}).status_code == 422


def test_commands_expire_after_60_s(alexa):
    store = alexa.app.state.alexa
    old = {"id": "c_0000000000001abcd", "kind": "clip_that", "game_id": "g_1", "t": 1.0,
           "created_at": time.time() - 61, "source": "alexa"}  # fmt: skip
    store.put("commands", {"commands": [old]})
    assert alexa.get("/tv/commands").json()["commands"] == []


def test_other_alexa_user_is_not_paired(alexa):
    _pair(alexa)
    env = _envelope(_intent("ClipThatIntent"), user="amzn1.ask.account.SOMEONEELSE")
    assert "isn't paired" in _speech(_post(alexa, env))


def test_pairing_attempts_are_limited(alexa):
    code = alexa.post("/tv/pair").json()["code"]
    wrong = "1000" if code != "1000" else "1001"
    for _ in range(alexa_routes.PAIR_TRIES - 1):
        assert "doesn't match" in _speech(_post(alexa, _envelope(_intent("PairIntent",
                                                                         code=wrong))))  # fmt: skip
    assert "too many tries" in _speech(_post(alexa, _envelope(_intent("PairIntent", code=wrong))))
    # the right code no longer works: the TV must show a new one
    late = _speech(_post(alexa, _envelope(_intent("PairIntent", code=code))))
    assert "isn't showing a pairing code" in late
    assert alexa.get("/tv/commands").json()["paired"] is False


def test_spoken_basics(alexa):
    help_ = _post(alexa, _envelope(_intent("AMAZON.HelpIntent"))).json()["response"]
    assert "clip that" in help_["outputSpeech"]["text"] and help_["shouldEndSession"] is False
    assert _speech(_post(alexa, _envelope(_intent("AMAZON.StopIntent")))) == "Okay."
    fb = _post(alexa, _envelope(_intent("AMAZON.FallbackIntent"))).json()["response"]
    assert fb["shouldEndSession"] is False
    assert "Say: pair code" in _speech(_post(alexa, _envelope(_intent("PairIntent"))))
    ended = _post(alexa, _envelope({"type": "SessionEndedRequest", "reason": "USER_INITIATED"}))
    assert ended.json() == {"version": "1.0", "response": {}}
    _pair(alexa)
    launch = _post(alexa, _envelope({"type": "LaunchRequest"})).json()["response"]
    assert launch["outputSpeech"]["text"].startswith("Replay court")
    assert launch["shouldEndSession"] is False


def test_export_reel_still_answers_when_the_reel_cannot_start(alexa, monkeypatch):
    from fastapi import HTTPException

    def no_render(*_a, **_k):
        raise HTTPException(503, "replay_worker is not available")

    monkeypatch.setattr(discovery_routes, "_submit", no_render)
    gid = new_game(alexa)
    _pair(alexa)
    alexa.post("/tv/state", json={"game_id": gid, "t": 3})
    assert "highlight reel" in _speech(_post(alexa, _envelope(_intent("ExportReelIntent"))))
    cmd = alexa.get("/tv/commands").json()["commands"][-1]
    assert cmd["kind"] == "export_reel" and cmd["reel"] is None


def test_cloud_mode_keeps_state_in_s3_and_reads_the_skill_id_from_ssm(request, chain, pki):
    """Cloud: the docs live under alexa/ in the bucket; the skill id comes from SSM when
    first needed (set after deploy: no redeploy)."""
    boto3 = pytest.importorskip("boto3")
    s3 = request.getfixturevalue("aws")  # test_cloud's moto fixtures
    s = dataclasses.replace(request.getfixturevalue("cloud_settings"), ssm_prefix="/replay/")
    with TestClient(create_app(s), headers={"X-Replay-Key": KEY}) as c:
        c.pki_key = pki["key"]  # type: ignore[attr-defined]
        env = _envelope({"type": "LaunchRequest"})
        assert _post(c, env).status_code == 400  # parameter not set yet
        boto3.client("ssm").put_parameter(Name="/replay/alexa-skill-id", Value=SKILL,
                                          Type="String")  # fmt: skip
        assert _post(c, env).status_code == 200
        gid = c.post("/games", json={"title": "Voice", "sport": "basketball"}).json()["id"]
        _pair(c)
        assert c.post("/tv/state", json={"game_id": gid, "t": 7, "playing": False}).is_success
        assert "clipping" in _speech(_post(c, _envelope(_intent("ClipThatIntent"))))
        cmds = c.get("/tv/commands").json()["commands"]
        assert [x["kind"] for x in cmds] == ["paired", "clip_that"] and cmds[1]["t"] == 7
        keys = {o["Key"] for o in s3.list_objects_v2(Bucket=BUCKET, Prefix="alexa/")["Contents"]}
        assert keys == {"alexa/pair.json", "alexa/link.json", "alexa/tv.json",
                        "alexa/commands.json"}  # fmt: skip
        # a second Lambda instance (fresh app) sees the same state
        with TestClient(create_app(s), headers={"X-Replay-Key": KEY}) as other:
            assert other.get("/tv/commands").json()["paired"] is True
