"""Alexa voice relay (docs/alexa.md): the custom skill's endpoint and the TV's side of it.

    POST /alexa                   the skill endpoint (Alexa-signed, no X-Replay-Key)
    POST /tv/pair                 -> {code, expires_at, paired}: 4 digits the TV shows, 5 min
    POST /tv/state                {game_id, t, playing}: heartbeat while a game is open
    GET  /tv/commands?after=<id>  -> {commands: [...], cursor, paired}; 60 s old ones dropped
    POST /tv/commands/{id}/ack    the TV handled it (never delivered again)
    POST /games/{g}/tv/play       {t}: the phone's "Play on the TV" (phone token), a `play` command

Alexa never reaches the TV: the skill writes a command, the TV polls for it. State is
five small JSON docs under `alexa/` (S3 in cloud mode, the data dir in local mode): `pair`
(the code), `link` (the paired Alexa user), `tv` (the heartbeat), `commands`, `acks`.
One TV per API key: a new pairing replaces the old one.
"""

from __future__ import annotations

import json
import logging
import re
import secrets
import threading
import time

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from . import alexa_verify, discovery_routes

log = logging.getLogger(__name__)
router = APIRouter()

PAIR_TTL_S = 300
PAIR_TRIES = 5  # wrong codes before the shown code is void
COMMAND_TTL_S = 60
FRESH_S = 30  # a heartbeat older than this: the TV is not watching
CID = re.compile(r"^c_\d{13}[0-9a-f]{4}$")

NOT_PAIRED = "Your TV isn't paired yet. Say: pair code, then the code on your TV."
NO_GAME = "Open a game on your TV first, then ask again."
WHAT = "You can say: clip that, or export a highlight reel."


class Store:
    """`alexa/{name}.json` docs. ponytail: the lock is per process; across Lambda
    instances the last write wins (one user, one TV, a few writes a minute)."""

    def __init__(self, settings, storage):
        self.s3 = storage.s3 if settings.cloud else None
        self.bucket = getattr(storage, "bucket", None)
        self.dir = settings.data_dir / "alexa"
        self.lock = threading.RLock()

    def get(self, name: str) -> dict:
        if self.s3 is None:
            p = self.dir / f"{name}.json"
            return json.loads(p.read_text()) if p.is_file() else {}
        try:
            body = self.s3.get_object(Bucket=self.bucket, Key=f"alexa/{name}.json")["Body"]
        except self.s3.exceptions.NoSuchKey:
            return {}
        return json.loads(body.read())

    def put(self, name: str, doc: dict) -> None:
        data = json.dumps(doc)
        if self.s3 is not None:
            self.s3.put_object(Bucket=self.bucket, Key=f"alexa/{name}.json",
                               Body=data.encode(), ContentType="application/json")  # fmt: skip
            return
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.dir / f"{name}.{secrets.token_hex(4)}.tmp"  # writers never share one
        tmp.write_text(data)
        tmp.replace(self.dir / f"{name}.json")


def _store(request: Request) -> Store:
    return request.app.state.alexa


def enqueue(store: Store, kind: str, game_id: str | None, t: float | None, **extra) -> dict:
    now = time.time()
    cmd = {"id": f"c_{int(now * 1000):013d}{secrets.token_hex(2)}", "kind": kind,
           "game_id": game_id, "t": t, "created_at": round(now, 3), "source": "alexa",
           **extra}  # fmt: skip
    with store.lock:
        live = [c for c in store.get("commands").get("commands", [])
                if now - c["created_at"] <= COMMAND_TTL_S]  # fmt: skip
        store.put("commands", {"commands": live + [cmd]})
    return cmd


# --------------------------------------------------------------------------- TV routes


class TvState(BaseModel):
    game_id: str | None = Field(default=None, pattern=r"^g_[0-9a-f]+$")
    t: float = Field(default=0.0, ge=0)
    playing: bool = False


@router.post("/tv/pair")
def tv_pair(request: Request):
    """A fresh code for the TV to show; any earlier code stops working."""
    store = _store(request)
    doc = {"code": str(1000 + secrets.randbelow(9000)), "expires_at": int(time.time()) + PAIR_TTL_S,
           "tries": 0}  # fmt: skip
    store.put("pair", doc)
    paired = bool(store.get("link").get("user_id"))
    return {"code": doc["code"], "expires_at": doc["expires_at"], "paired": paired}


@router.post("/tv/state")
def tv_state(request: Request, body: TvState):
    _store(request).put("tv", {**body.model_dump(), "at": round(time.time(), 3)})
    return {"ok": True}


@router.get("/tv/commands")
def tv_commands(request: Request, after: str = ""):
    store, now = _store(request), time.time()
    acked = set(store.get("acks").get("ids", []))
    cmds = [c for c in store.get("commands").get("commands", [])
            if c["id"] > after and c["id"] not in acked
            and now - c["created_at"] <= COMMAND_TTL_S]  # fmt: skip
    return {"commands": cmds, "cursor": cmds[-1]["id"] if cmds else after,
            "paired": bool(store.get("link").get("user_id"))}  # fmt: skip


@router.post("/tv/commands/{cid}/ack")
def tv_ack(request: Request, cid: str):
    if not CID.match(cid):
        raise HTTPException(404, f"command {cid} not found")
    store = _store(request)
    with store.lock:
        ids = store.get("acks").get("ids", [])
        if cid not in ids:
            store.put("acks", {"ids": (ids + [cid])[-50:]})
    return {"id": cid, "acked": True}


class PlayIn(BaseModel):
    t: float = Field(ge=0)


@router.post("/games/{game_id}/tv/play", status_code=202)
def tv_play(request: Request, game_id: str, body: PlayIn):
    """The phone's "Play on the TV" (a search hit, phone token): a `play` command for this
    game, which the TV's open Watch picks up from GET /tv/commands and acks. `tv`: a TV is
    showing this game now (a fresh POST /tv/state), so the phone plays it there, not inline."""
    if request.app.state.index.load(game_id) is None:
        raise HTTPException(404, f"game {game_id} not found")
    store = _store(request)
    cmd = enqueue(store, "play", game_id, round(body.t, 2), source="phone")
    tv = store.get("tv")
    showing = tv.get("game_id") == game_id and time.time() - tv.get("at", 0) <= FRESH_S
    return {"id": cmd["id"], "queued": True, "tv": showing}


# --------------------------------------------------------------------------- the skill


def _say(text: str, end: bool = True) -> dict:
    out = {"outputSpeech": {"type": "PlainText", "text": text}, "shouldEndSession": end}
    if not end:
        out["reprompt"] = {"outputSpeech": {"type": "PlainText", "text": WHAT}}
    return {"version": "1.0", "response": out}


def _skill_id(state) -> str | None:
    """Env/settings, else SSM `{prefix}alexa-skill-id` (looked up until found, so setting
    the parameter needs no redeploy)."""
    s = state.settings
    if not state.alexa_skill_id and s.cloud and s.ssm_prefix:
        import boto3

        ssm = boto3.client("ssm")
        try:
            got = ssm.get_parameter(Name=f"{s.ssm_prefix}alexa-skill-id")
            state.alexa_skill_id = got["Parameter"]["Value"].strip()
        except ssm.exceptions.ParameterNotFound:
            log.warning("alexa: %salexa-skill-id is not set", s.ssm_prefix)
    return state.alexa_skill_id


def _pair(store: Store, user: str, code: str) -> str:
    code = re.sub(r"\D", "", code or "")
    if not code:
        return "Say: pair code, then the four digits on your TV."
    now = time.time()
    with store.lock:
        p = store.get("pair")
        if not p.get("code") or p["expires_at"] < now:
            return ("Your TV isn't showing a pairing code. On your TV, open Settings, "
                    "then Pair with Alexa, and try again.")  # fmt: skip
        if code != p["code"]:
            p["tries"] = p.get("tries", 0) + 1
            if p["tries"] >= PAIR_TRIES:
                store.put("pair", {})
                return "That's too many tries. Show a new code on your TV, then try again."
            store.put("pair", p)
            return "That code doesn't match your TV. Check the code on screen and try again."
        store.put("pair", {})  # one use
    store.put("link", {"user_id": user, "paired_at": round(now, 3)})
    enqueue(store, "paired", None, None)
    return "Paired with your TV. Now say: Alexa, ask replay court to clip that."


def _start_reel(request: Request, game_id: str) -> dict | None:
    """The reel job, queued now so the phone page finds it under way (no render here)."""
    try:
        out = discovery_routes.post_reel(request, game_id, discovery_routes.ReelIn(), Response())
    except HTTPException as exc:  # unknown game, render code missing
        log.warning("alexa: reel not started: %s", exc.detail)
        return None
    return {"id": out["id"], "status": out["status"]}


def _command(request: Request, user: str, kind: str) -> str:
    store = _store(request)
    if not user or store.get("link").get("user_id") != user:
        return NOT_PAIRED
    tv, now = store.get("tv"), time.time()
    if not tv.get("game_id") or now - tv.get("at", 0) > FRESH_S:
        return NO_GAME
    t = tv["t"] + (now - tv["at"] if tv.get("playing") else 0.0)
    extra = {}
    if kind == "export_reel":
        extra["reel"] = _start_reel(request, tv["game_id"])
    enqueue(store, kind, tv["game_id"], round(t, 3), **extra)
    if kind == "clip_that":
        return "Okay, clipping that on your TV."
    status = (extra["reel"] or {}).get("status")
    if status == "done":
        return "Your highlight reel is ready. Scan the code on your TV to get it on your phone."
    if status in ("queued", "running"):
        return "Okay, making your highlight reel. Scan the code on your TV to get it on your phone."
    return "Okay. Scan the code on your TV to make your highlight reel on your phone."


def handle(request: Request, req: dict) -> dict:
    r = req.get("request") or {}
    rtype = r.get("type")
    system = (req.get("context") or {}).get("System") or {}
    user = (system.get("user") or (req.get("session") or {}).get("user") or {}).get("userId")
    store = _store(request)
    if rtype == "SessionEndedRequest":
        return {"version": "1.0", "response": {}}
    if rtype == "LaunchRequest":
        paired = user and store.get("link").get("user_id") == user
        return _say(f"Replay court. {WHAT}" if paired else NOT_PAIRED, end=not paired)
    name = (r.get("intent") or {}).get("name") if rtype == "IntentRequest" else None
    log.info("alexa: %s %s", rtype, name)
    if name == "PairIntent":
        slot = ((r["intent"].get("slots") or {}).get("code") or {}).get("value")
        return _say(_pair(store, user, slot))
    if name == "ExportReelIntent":
        return _say(_command(request, user, "export_reel"))
    if name == "ClipThatIntent":
        return _say(_command(request, user, "clip_that"))
    if name in ("AMAZON.StopIntent", "AMAZON.CancelIntent", "AMAZON.NavigateHomeIntent"):
        return _say("Okay.")
    if name == "AMAZON.HelpIntent":
        return _say(f"{WHAT} To pair a TV, say: pair code, then the code on your TV.", end=False)
    return _say(f"Sorry, I can't do that. {WHAT}", end=False)


def _app_id(req: dict) -> str | None:
    system = (req.get("context") or {}).get("System") or {}
    app = system.get("application") or (req.get("session") or {}).get("application") or {}
    return app.get("applicationId")


@router.post("/alexa")
async def alexa(request: Request):
    body = await request.body()  # the exact signed bytes
    h = request.headers
    try:
        req = await run_in_threadpool(
            alexa_verify.verify, h.get("signaturecertchainurl"), h.get("signature-256"), body
        )
    except alexa_verify.Invalid as exc:
        log.warning("alexa: rejected: %s", exc)
        return JSONResponse({"detail": "invalid Alexa request"}, 400)
    skill = await run_in_threadpool(_skill_id, request.app.state)
    if not skill or _app_id(req) != skill:
        log.warning("alexa: rejected: skill id %s", "not configured" if not skill else "differs")
        return JSONResponse({"detail": "invalid Alexa request"}, 400)
    return await run_in_threadpool(handle, request, req)
