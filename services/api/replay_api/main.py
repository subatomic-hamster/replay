"""Replay API v1 — every route in plan §4.6, local providers only."""

from __future__ import annotations

import copy
import json
import logging
import secrets
from typing import Any

from fastapi import (
    Body,
    FastAPI,
    File,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from . import pipeline_adapter as adapter
from . import stats as stats_mod
from .config import Settings, from_env
from .providers.index import LocalIndex
from .providers.jobs import LocalJobs
from .providers.labeler import get_labeler
from .providers.query import get_query_engine, merged_vocab
from .providers.storage import LocalStorage

log = logging.getLogger(__name__)

EVENTS_REL = "events.json"
THUMB_REL = "media/thumb.jpg"
CALIB_REL = "media/calib.jpg"
# D-23: the *proposal*, not the calibration. POST /calibration is still the commit.
AUTOCALIB_REL = "autocalib.json"
SOURCE_REL = "source.mp4"
EVENT_FIELDS = {
    "type",
    "made",
    "t_start",
    "t_key",
    "t_end",
    "player_id",
    "court",
    "confidence",
    "confirmed",
    "contacts",
    "winner_side",
    # D-11: "not a shot" in the review queue. Additive and optional; `replay.events.v1`
    # allows extra keys, so courtcam still reads a file the API rewrote.
    "dismissed",
}


def live_events(events: list[dict]) -> list[dict]:
    """D-11: dismissed events stay in the file but never reach query or stats."""
    return [e for e in events if not e.get("dismissed")]


# --------------------------------------------------------------------------- models


class GameCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    sport: str = "basketball"


class Calibration(BaseModel):
    sport: str
    variant: str
    landmarks_px: dict[str, tuple[float, float]]


class AutoCalibration(BaseModel):
    """D-23: ask a vision model where the landmarks are. Nothing is committed by this."""

    sport: str
    variant: str
    backend: str | None = None


class PlayerPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    merge_into: str | None = None


class BookmarkCreate(BaseModel):
    t: float = Field(ge=0)


class QueryIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)


# --------------------------------------------------------------------------- helpers


def _base(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _ctx(request: Request):
    return request.app.state


def _game_or_404(request: Request, game_id: str) -> dict:
    game = _ctx(request).index.load(game_id)
    if game is None:
        raise HTTPException(404, f"game {game_id} not found")
    return game


def _events(storage: LocalStorage, game_id: str) -> list[dict]:
    p = storage.path(game_id, EVENTS_REL)
    if not p.is_file():
        return []
    return json.loads(p.read_text()).get("events", [])


def _save_events(storage: LocalStorage, game_id: str, events: list[dict]) -> None:
    storage.write_json(game_id, EVENTS_REL, {"schema": "replay.events.v1", "events": events})


def _track_frames(storage: LocalStorage, game_id: str):
    for chunk in sorted(storage.path(game_id, "tracks").glob("*.json")):
        try:
            yield from json.loads(chunk.read_text()).get("frames", [])
        except ValueError:
            log.warning("skipping malformed track chunk %s", chunk)


def _resolve_urls(game: dict, storage: LocalStorage, base: str) -> dict:
    g = copy.deepcopy(game)
    gid = g["id"]

    def url(rel: str) -> str:
        return storage.url(gid, rel, base)

    rend = g.get("renditions") or {}
    if rend.get("wide"):
        rend["wide"] = url(rend["wide"])
    rend["players"] = {k: url(v) for k, v in (rend.get("players") or {}).items()}
    g["renditions"] = rend
    for key in ("tracks", "croppaths"):
        block = g.get(key)
        if block and block.get("url_template"):
            block["url_template"] = url(block["url_template"])
    if g.get("events_url"):
        g["events_url"] = url(g["events_url"])
    # D-13/D-14: not §4.5 game.json fields, but the uploader and the library need them.
    thumb = _thumbnail_rel(g, storage)
    g["thumb_url"] = url(thumb) if thumb else None
    g["calib_url"] = url(CALIB_REL) if storage.path(gid, CALIB_REL).is_file() else None
    variant = (g.get("court") or {}).get("variant")
    g["sport_ui"] = (adapter.get_profile(g.get("sport") or "", variant) or {}).get("sport_ui")
    return g


def _active_job(jobs: LocalJobs, game_id: str) -> dict | None:
    """The queued/running `process` job for this game, if any."""
    live = [
        j
        for j in jobs.for_game(game_id)
        if j.get("kind") == "process" and j.get("status") in ("queued", "running")
    ]
    return max(live, key=lambda j: j.get("created_at") or 0.0) if live else None


def _autocalib_job(jobs: LocalJobs, game_id: str) -> dict | None:
    """The newest `autocalib` job for this game, running or finished."""
    mine = [j for j in jobs.for_game(game_id) if j.get("kind") == "autocalib"]
    return max(mine, key=lambda j: j.get("created_at") or 0.0) if mine else None


def _court_or_400(sport: str, variant: str) -> dict:
    """The profile's `court` block, or a 400. Shared by the calibration commit and the
    auto-calibration job: the job used to validate only the sport, so a variant the
    profile has never heard of was swallowed and only surfaced as a failed proposal."""
    profile = adapter.get_profile(sport)
    if profile is None:
        raise HTTPException(400, f"unknown sport {sport!r}")
    court = profile.get("court") or {}
    variants = court.get("variants") or []
    # A retired name (badminton `singles`) still posts: courtcam maps it to its variant.
    if variants and variant not in [*variants, *(court.get("variant_aliases") or {})]:
        raise HTTPException(400, f"variant must be one of {variants}")
    return court


def _autocalib_backend(settings: Settings, requested: str | None) -> str:
    """`fake` in fake-pipeline mode unless something explicitly asked for otherwise."""
    if requested:
        return requested
    if settings.autocalib_backend != "auto":
        return settings.autocalib_backend
    return "fake" if settings.pipeline == "fake" else "auto"


def _with_job_progress(game: dict, jobs: LocalJobs) -> dict:
    """D-9: courtcam owns game.json while it runs, so live stage state comes from the
    job record (data/jobs.json), merged in on read. Additive `progress` carries the
    per-stage fraction the job last reported."""
    job = _active_job(jobs, game["id"])
    if job is None:
        return game
    names = list(game.get("stages") or adapter.FAKE_STAGES)
    at = names.index(job["stage"]) if job.get("stage") in names else -1
    fraction = min(1.0, max(0.0, float(job.get("fraction") or 0.0)))
    stages, progress = {}, {}
    for i, name in enumerate(names):
        if i < at:
            stages[name], progress[name] = "done", 1.0
        elif i > at or at < 0:
            stages[name], progress[name] = "pending", 0.0
        else:
            stages[name] = "done" if fraction >= 1.0 else "running"
            progress[name] = fraction
    game["stages"] = stages
    game["progress"] = progress
    game["status"] = "processing"
    return game


def _thumbnail_rel(game: dict, storage: LocalStorage) -> str | None:
    """Both courtcam and fake mode write `media/thumb.jpg`; it is not a game.json field."""
    rel = game.get("thumbnail") or THUMB_REL
    return rel if storage.path(game["id"], rel).is_file() else None


def _summary(game: dict, storage: LocalStorage, base: str) -> dict:
    thumb = _thumbnail_rel(game, storage)
    # `progress` rides along only while a job is running, same as GET /games/{id}.
    extra = {"progress": game["progress"]} if game.get("progress") else {}
    return {
        **extra,
        "id": game["id"],
        "title": game.get("title"),
        "status": game.get("status"),
        "stages": game.get("stages"),
        "duration_s": (game.get("video") or {}).get("duration_s"),
        "thumb_url": storage.url(game["id"], thumb, base) if thumb else None,
        "recorded_at": game.get("recorded_at"),
        "sport": game.get("sport"),
    }


# --------------------------------------------------------------------------- app


def create_app(settings: Settings | None = None) -> FastAPI:
    s = settings or from_env()
    if s.storage != "local" or s.jobs != "local":
        raise ValueError("Phase 1 supports REPLAY_STORAGE=local and REPLAY_JOBS=local only")
    s.data_dir.mkdir(parents=True, exist_ok=True)

    app = FastAPI(title="Replay API", version="1.0")
    app.state.settings = s
    app.state.storage = LocalStorage(s.games_dir)
    app.state.index = LocalIndex(app.state.storage)
    app.state.jobs = LocalJobs(s.jobs_state_path)
    app.state.labeler = get_labeler(s.labeler)
    app.state.query = get_query_engine(s.query)
    app.state.sessions: dict[str, dict] = {}

    @app.middleware("http")
    async def require_key(request: Request, call_next):
        path = request.url.path
        open_route = path.startswith("/media/") or path == "/healthz"
        if s.api_key and not open_route and request.headers.get("x-replay-key") != s.api_key:
            return JSONResponse({"detail": "missing or invalid X-Replay-Key"}, 401)
        return await call_next(request)

    # added last => outermost, so preflight works even when auth would reject
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_origins,
        allow_credentials="*" not in s.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Range", "Accept-Ranges", "Content-Length"],
    )

    _register_routes(app)
    return app


def _register_routes(app: FastAPI) -> None:
    @app.get("/healthz")
    def healthz(request: Request):
        s: Settings = _ctx(request).settings
        return {
            "ok": True,
            "providers": {
                "storage": s.storage,
                "jobs": s.jobs,
                "labeler": s.labeler,
                "query": s.query,
                "pipeline": s.pipeline,
            },
            "auth": bool(s.api_key),
        }

    @app.get("/sports")
    def sports():
        return adapter.list_sports()

    # ---------------------------------------------------------------- games

    @app.post("/games", status_code=201)
    def create_game(request: Request, body: GameCreate):
        if adapter.get_profile(body.sport) is None:
            raise HTTPException(400, f"unknown sport {body.sport!r}")
        game = _ctx(request).index.create(body.title, body.sport)
        return {"id": game["id"], "upload_url": f"{_base(request)}/games/{game['id']}/upload"}

    @app.get("/games")
    def list_games(request: Request):
        ctx = _ctx(request)
        base = _base(request)
        return [
            _summary(_with_job_progress(g, ctx.jobs), ctx.storage, base) for g in ctx.index.list()
        ]

    @app.get("/games/{game_id}")
    def get_game(request: Request, game_id: str):
        ctx = _ctx(request)
        game = _game_or_404(request, game_id)
        return _with_job_progress(_resolve_urls(game, ctx.storage, _base(request)), ctx.jobs)

    @app.put("/games/{game_id}/upload")
    async def upload_put(request: Request, game_id: str):
        game = _game_or_404(request, game_id)
        dest = _ctx(request).storage.path(game_id, SOURCE_REL)
        dest.parent.mkdir(parents=True, exist_ok=True)
        size = 0
        with dest.open("wb") as fh:
            async for chunk in request.stream():
                size += len(chunk)
                fh.write(chunk)
        return _finish_upload(request, game, size)

    @app.post("/games/{game_id}/upload")
    async def upload_post(
        # B008: a call in a default is how FastAPI declares a dependency
        request: Request,
        game_id: str,
        file: UploadFile = File(...),  # noqa: B008
    ):
        game = _game_or_404(request, game_id)
        dest = _ctx(request).storage.path(game_id, SOURCE_REL)
        dest.parent.mkdir(parents=True, exist_ok=True)
        size = 0
        with dest.open("wb") as fh:
            while chunk := await file.read(1 << 20):
                size += len(chunk)
                fh.write(chunk)
        return _finish_upload(request, game, size)

    def _finish_upload(request: Request, game: dict, size: int) -> dict:
        if size == 0:
            _ctx(request).storage.path(game["id"], SOURCE_REL).unlink(missing_ok=True)
            raise HTTPException(400, "empty upload")
        # D-14: calibration happens before processing, so the frame to click on has to
        # exist now. One ffmpeg -frames:v 1 on a local file, ~100 ms.
        storage = _ctx(request).storage
        adapter.grab_frame(
            storage.path(game["id"], SOURCE_REL), storage.path(game["id"], CALIB_REL), 5.0
        )
        game["status"] = "uploaded"
        _ctx(request).index.save(game)
        return {"id": game["id"], "size": size, "status": "uploaded"}

    @app.post("/games/{game_id}/calibration")
    def calibrate(request: Request, game_id: str, body: Calibration):
        game = _game_or_404(request, game_id)
        court = _court_or_400(body.sport, body.variant)

        marks = body.landmarks_px
        # D-19: a homography needs 4 points the *template* knows, not specifically the 4
        # corners. On real wide footage a corner is routinely off-frame (D-18), which is
        # exactly what the profile's `landmarks_optional` exist for. courtcam's
        # reprojection gate below is the real check; this one only catches an empty click
        # set or points from some other sport.
        known = set(court.get("landmarks") or []) | set(court.get("landmarks_optional") or [])
        usable = sorted(set(marks) & known) if known else sorted(marks)
        if len(usable) < 4:
            raise HTTPException(400, f"at least 4 known landmarks are required, got {usable}")

        try:
            fit = adapter.calibration_error(
                body.sport,
                body.variant,
                marks,
                game.get("video"),
                _ctx(request).storage.path(game_id, CALIB_REL),
            )
        except adapter.CalibrationRejected as exc:
            raise HTTPException(400, str(exc)) from exc

        game["sport"] = body.sport
        game["court"] = {
            "variant": body.variant,
            "standard": court.get("standard", "fiba"),
            "landmarks_px": {k: list(v) for k, v in marks.items()},
        }
        game["status"] = (
            "calibrated" if game["status"] in ("created", "uploaded") else game["status"]
        )
        _ctx(request).index.save(game)
        return {
            "id": game_id,
            "court": game["court"],
            "reprojection_error_px": fit["reprojection_error_px"],
            # Per-landmark, so the uploader can name the worst click (bug 3).
            "residuals_px": fit["residuals_px"],
            # Additive (D-25): the lens model the pipeline will use, and what it bought.
            "k1": fit["k1"],
            "lens_rms_px": fit["lens_rms_px"],
        }

    @app.post("/games/{game_id}/calibration/auto", status_code=202)
    def calibrate_auto(request: Request, game_id: str, body: AutoCalibration):
        """D-23: queue a landmark proposal. 10-180 s, so the client polls the GET.

        This never becomes the game's calibration on its own — the client still POSTs
        `/calibration` with the points it accepted, edits included.
        """
        ctx = _ctx(request)
        _game_or_404(request, game_id)
        if not ctx.storage.path(game_id, CALIB_REL).is_file():
            raise HTTPException(400, "no calibration frame yet — upload the video first")
        # Same gate as POST /calibration: a bad variant used to be swallowed here and
        # only surface as a failed proposal much later.
        _court_or_400(body.sport, body.variant)
        live = _autocalib_job(ctx.jobs, game_id)
        if live is not None and live["status"] in ("queued", "running"):
            return {"job_id": live["id"], "status": live["status"], "game_id": game_id}
        ctx.storage.path(game_id, AUTOCALIB_REL).unlink(missing_ok=True)
        job = ctx.jobs.submit(
            "autocalib",
            game_id,
            _autocalib_task(
                ctx.settings,
                ctx.storage,
                game_id,
                body.sport,
                body.variant,
                _autocalib_backend(ctx.settings, body.backend),
            ),
        )
        return {"job_id": job["id"], "status": job["status"], "game_id": game_id}

    @app.get("/games/{game_id}/calibration/auto")
    def calibrate_auto_status(request: Request, game_id: str):
        ctx = _ctx(request)
        _game_or_404(request, game_id)
        job = _autocalib_job(ctx.jobs, game_id)
        result = ctx.storage.path(game_id, AUTOCALIB_REL)
        if result.is_file():
            proposal = json.loads(result.read_text())
            return {
                "status": "done",
                "proposal": proposal,
                "ok": bool(proposal.get("ok")),
                "reprojection_error_px": proposal.get("reprojection_error_px"),
            }
        if job is None:
            return {"status": "idle", "ok": False}
        if job["status"] == "failed":
            return {"status": "failed", "ok": False, "error": job.get("error")}
        return {"status": job["status"], "ok": False}

    @app.post("/games/{game_id}/process", status_code=202)
    def process(request: Request, game_id: str):
        ctx = _ctx(request)
        game = _game_or_404(request, game_id)
        if not ctx.storage.path(game_id, SOURCE_REL).is_file():
            raise HTTPException(400, "no video uploaded for this game")
        if not game.get("court"):
            raise HTTPException(400, "game must be calibrated before processing")
        # Idempotent: a double tap on "Start processing" must not queue a second run.
        running = _active_job(ctx.jobs, game_id)
        if running is not None:
            return {"job_id": running["id"], "status": running["status"], "game_id": game_id}
        # S-08: the stage list is the pipeline's own (courtcam reports nine, fake mode
        # five), so the status page renders whatever keys arrive, in this order. Saved
        # before the job is queued, so the task and the read path both see it.
        game["stages"] = dict.fromkeys(adapter.stage_names(ctx.settings.pipeline), "pending")
        game["status"] = "queued"
        ctx.index.save(game)
        job = ctx.jobs.submit(
            "process",
            game_id,
            _process_task(ctx.settings, ctx.storage, ctx.index, ctx.jobs, game_id),
        )
        return {"job_id": job["id"], "status": job["status"], "game_id": game_id}

    # ---------------------------------------------------------------- players

    @app.patch("/games/{game_id}/players/{player_id}")
    def patch_player(request: Request, game_id: str, player_id: str, body: PlayerPatch):
        ctx = _ctx(request)
        game = _game_or_404(request, game_id)
        players = game.get("players") or []
        player = next((p for p in players if p["id"] == player_id), None)
        if player is None:
            raise HTTPException(404, f"player {player_id} not found")
        if body.name is None and body.merge_into is None:
            raise HTTPException(400, "provide `name` and/or `merge_into`")

        if body.name is not None:
            player["name"] = body.name
            player["tagged"] = True

        if body.merge_into is not None:
            target = next((p for p in players if p["id"] == body.merge_into), None)
            if target is None:
                raise HTTPException(404, f"player {body.merge_into} not found")
            if target["id"] == player_id:
                raise HTTPException(400, "cannot merge a player into itself")
            _merge_player(ctx.storage, game, player_id, target["id"])
            game["players"] = [p for p in players if p["id"] != player_id]

        ctx.index.save(game)
        return _resolve_urls(game, ctx.storage, _base(request))

    @app.post("/games/{game_id}/players/{player_id}/render", status_code=202)
    def render_player(request: Request, game_id: str, player_id: str):
        ctx = _ctx(request)
        game = _game_or_404(request, game_id)
        if not any(p["id"] == player_id for p in game.get("players") or []):
            raise HTTPException(404, f"player {player_id} not found")
        job = ctx.jobs.submit(
            "render",
            game_id,
            _render_task(ctx.settings, ctx.storage, ctx.index, game_id, player_id),
        )
        return {"job_id": job["id"], "status": job["status"], "player_id": player_id}

    # ---------------------------------------------------------------- events

    @app.patch("/games/{game_id}/events/{event_id}")
    def patch_event(
        request: Request,
        game_id: str,
        event_id: str,
        body: dict[str, Any] = Body(...),  # noqa: B008
    ):
        ctx = _ctx(request)
        _game_or_404(request, game_id)
        unknown = sorted(set(body) - EVENT_FIELDS)
        if unknown:
            raise HTTPException(400, f"unsupported event fields: {', '.join(unknown)}")
        events = _events(ctx.storage, game_id)
        event = next((e for e in events if e["id"] == event_id), None)
        if event is None:
            raise HTTPException(404, f"event {event_id} not found")

        changed = {k: v for k, v in body.items() if k != "confirmed" and event.get(k) != v}
        event.update(body)
        event["confirmed"] = bool(body.get("confirmed", True))
        if changed:
            event["source"] = "user"  # §4.5: user-corrected fields are sourced to the user
        _save_events(ctx.storage, game_id, events)
        return event

    @app.post("/games/{game_id}/events", status_code=201)
    def create_bookmark(request: Request, game_id: str, body: BookmarkCreate):
        ctx = _ctx(request)
        game = _game_or_404(request, game_id)
        duration = (game.get("video") or {}).get("duration_s") or 0.0
        events = _events(ctx.storage, game_id)
        event = {
            "id": "e_" + secrets.token_hex(4),
            "type": "bookmark",
            "t_start": round(max(0.0, body.t - 3.0), 3),
            "t_key": round(body.t, 3),
            "t_end": round(min(body.t + 2.0, duration) if duration else body.t + 2.0, 3),
            "player_id": None,
            "confidence": 1.0,
            "source": "user",
            "confirmed": True,
        }
        events.append(event)
        _save_events(ctx.storage, game_id, events)
        return event

    # ---------------------------------------------------------------- query & stats

    @app.post("/games/{game_id}/query")
    def query(request: Request, game_id: str, body: QueryIn):
        ctx = _ctx(request)
        game = _game_or_404(request, game_id)
        profile = adapter.get_profile(game.get("sport", "")) or {}
        engine = get_query_engine(ctx.settings.query, merged_vocab(profile.get("query_vocab")))
        return engine.query(body.text, game, live_events(_events(ctx.storage, game_id)))

    @app.get("/games/{game_id}/stats")
    def game_stats(request: Request, game_id: str):
        ctx = _ctx(request)
        game = _game_or_404(request, game_id)
        return stats_mod.compute(
            game,
            live_events(_events(ctx.storage, game_id)),
            _track_frames(ctx.storage, game_id),
            adapter.get_profile(game.get("sport", ""), (game.get("court") or {}).get("variant")),
        )

    # ---------------------------------------------------------------- sessions

    @app.post("/sessions", status_code=201)
    def create_session(request: Request):
        sid = "s_" + secrets.token_hex(4)
        code = f"{secrets.randbelow(10000):04d}"
        _ctx(request).sessions[sid] = {"code": code, "clients": set()}
        return {"id": sid, "code": code}

    @app.websocket("/sessions/{sid}")
    async def session_ws(ws: WebSocket, sid: str):
        # D-16: `sid` may also be the 4-digit pairing code, so the phone companion
        # needs no code->id lookup route.
        sessions: dict[str, dict] = ws.app.state.sessions
        session = sessions.get(sid) or next(
            (s for s in sessions.values() if s["code"] == sid), None
        )
        if session is None:
            await ws.close(code=4404)
            return
        await ws.accept()
        session["clients"].add(ws)
        try:
            while True:
                msg = await ws.receive_text()
                for peer in list(session["clients"]):
                    if peer is not ws:
                        await peer.send_text(msg)
        except WebSocketDisconnect:
            pass
        finally:
            session["clients"].discard(ws)

    # ---------------------------------------------------------------- media

    @app.get("/media/games/{game_id}/{rel_path:path}")
    def media(request: Request, game_id: str, rel_path: str):
        storage: LocalStorage = _ctx(request).storage
        if not game_id.replace("_", "").isalnum():
            raise HTTPException(404, "not found")
        target = storage.resolve_inside(game_id, rel_path)
        if target is None or not target.is_file():
            raise HTTPException(404, "not found")
        # Starlette's FileResponse serves HTTP Range itself (206 + Content-Range).
        return FileResponse(target)


# --------------------------------------------------------------------------- jobs


def _autocalib_task(
    settings: Settings,
    storage: LocalStorage,
    game_id: str,
    sport: str,
    variant: str,
    backend: str,
):
    """Runs on the jobs worker thread — the model call is 10-180 s of waiting."""

    def task(job_id: str) -> None:
        del job_id
        storage.write_json(
            game_id,
            AUTOCALIB_REL,
            adapter.autocalibrate(
                storage.path(game_id, CALIB_REL),
                sport,
                variant,
                backend=backend,
                fake_dir=settings.fake_pipeline_dir,
                fake_delay_s=settings.fake_pipeline_delay_s,
            ),
        )

    return task


def _process_task(
    settings: Settings, storage: LocalStorage, index: LocalIndex, jobs: LocalJobs, game_id: str
):
    def task(job_id: str) -> None:
        base = index.load(game_id)
        if base is None:
            raise FileNotFoundError(f"game {game_id} disappeared")
        base["status"] = "processing"
        base["stages"] = {k: "pending" for k in base["stages"]}
        index.save(base)

        # courtcam rewrites game.json after every stage, so the API must not write it
        # during the run: stage progress goes to the job record instead.
        last = {"stage": "", "frac": -1.0}

        def progress(stage: str, frac: float) -> None:
            if stage in base["stages"]:
                base["stages"][stage] = "done" if frac >= 1.0 else "running"
            if stage != last["stage"] or frac - last["frac"] >= 0.05 or frac >= 1.0:
                last.update(stage=stage, frac=frac)
                jobs.progress(job_id, stage, frac)

        try:
            produced = adapter.run(
                input_path=storage.path(game_id, SOURCE_REL),
                out_dir=storage.game_dir(game_id),
                game=base,
                progress=progress,
                pipeline=settings.pipeline,
                fake_dir=settings.fake_pipeline_dir,
                detector=settings.detector,
                fake_delay_s=settings.fake_pipeline_delay_s,
            )
        except Exception:
            base["status"] = "failed"
            index.save(copy.deepcopy(base))
            raise
        merged = {**base, **produced}
        merged["stages"] = {k: "done" for k in base["stages"]}
        merged["status"] = "ready"
        index.save(merged)

    return task


def _render_task(
    settings: Settings, storage: LocalStorage, index: LocalIndex, game_id: str, player_id: str
):
    def task(job_id: str) -> None:
        rel = adapter.render_player(
            game_dir=storage.game_dir(game_id),
            player_id=player_id,
            progress=lambda stage, frac: None,
            pipeline=settings.pipeline,
        )
        game = index.load(game_id)
        if game is None:
            return
        rend = game.setdefault("renditions", {"wide": None, "players": {}})
        rend.setdefault("players", {})
        if rel:
            rend["players"][player_id] = rel
        game.setdefault("stages", {})["render"] = "partial" if rel else game["stages"].get("render")
        index.save(game)

    return task


def _merge_player(storage: LocalStorage, game: dict, src: str, dst: str) -> None:
    """Rewrite `src` -> `dst` in tracks chunks + events; drop src's crops/rendition.

    Rewriting is cheap (a few KB per 10 s chunk) and leaves no alias map for every
    client to reimplement.
    """
    gid = game["id"]
    for chunk in sorted(storage.path(gid, "tracks").glob("*.json")):
        data = json.loads(chunk.read_text())
        for frame in data.get("frames", []):
            keep: dict[str, dict] = {}
            for entry in frame.get("p", []):
                if entry.get("id") == src:
                    entry["id"] = dst
                prev = keep.get(entry["id"])
                # a frame can now hold two boxes for dst; keep the confident one
                if prev is None or (entry.get("c") or 0) > (prev.get("c") or 0):
                    keep[entry["id"]] = entry
            frame["p"] = list(keep.values())
        chunk.write_text(json.dumps(data))

    events = _events(storage, gid)
    for event in events:
        if event.get("player_id") == src:
            event["player_id"] = dst
    if events:
        _save_events(storage, gid, events)

    storage.path(gid, f"crops/{src}.json").unlink(missing_ok=True)
    (game.get("renditions") or {}).get("players", {}).pop(src, None)


def __getattr__(name: str):
    """`uvicorn replay_api.main:app` builds the app on first access, so importing this
    module (tests, tooling) has no side effects."""
    if name == "app":
        global _app
        _app = globals().get("_app") or create_app()
        return _app
    raise AttributeError(name)
