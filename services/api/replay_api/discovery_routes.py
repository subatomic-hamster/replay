"""M11 endpoints (additive): hype meter, rally browser + condensed game, vertical share
exports, and the post-game review queue.

The maths and the renders live in the replay-side `replay_render` package (render/) and
the worker's `discovery` stages (services/worker); both are imported lazily, as the API
runs without them in fake mode — the routes that need them then answer 503. Renders run
as API jobs through the worker DAG with a one-stage registry, so they are cache-keyed on
their inputs: asking twice for the same export is one render.

    GET  /games/{id}/hype                    hype.json (stored by the `hype` stage, else computed)
    GET  /games/{id}/rallies                 rally browser (+ condensed offsets once rendered)
    POST /games/{id}/condensed               render renditions/condensed.mp4 (202 + job)
    GET  /games/{id}/condensed               its status and URL
    POST /games/{id}/exports/vertical        {clip_id | play_id | event_id | t_start+t_end,
                                              player_id?} -> 200 done / 202 queued
    GET  /games/{id}/exports/vertical[/{vid}]
    POST /games/{id}/exports/reel            {aspect: "16:9" | "9:16"} -> 200 done or
                                              in progress / 202 queued (highlight reel)
    GET  /games/{id}/exports/reel[/{rid}]    status, url, segments
    GET  /games/{id}/review/queue            questions answered with existing PATCH routes
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from . import stats as stats_mod

router = APIRouter()
HYPE_REL = "hype.json"
CONDENSED_REL = "renditions/condensed.mp4"
CONDENSED_DOC = "condensed.json"
VERTICAL_DIR = "exports/vertical"
VID = re.compile(r"^v_[0-9a-f]{12}$")
REEL_DIR = "exports/reel"
RID = re.compile(r"^r_[0-9a-f]{12}$")
# what a reel's plan is made from (replay_render.reel): a change to any is a new reel
REEL_INPUTS = (
    "game.json",
    "events.json",
    "plays.json",
    "hype.json",
    "clips.json",
    "triggers.json",
    "edits.json",
)  # fmt: skip (edits.json: the best-play pick)


class VerticalIn(BaseModel):
    clip_id: str | None = None
    play_id: str | None = None
    event_id: str | None = None
    t_start: float | None = Field(default=None, ge=0)
    t_end: float | None = Field(default=None, gt=0)
    player_id: str | None = None


# what replay_render.gamedata.load_game reads
GAMEDATA = ("game.json", "calib.json", "tracks", "events.json", "score.json", "plays.json")


def _game(request: Request, game_id: str, *rels: str) -> tuple[dict, Path]:
    """The game and its folder with only `rels` current: on S3 a route pulls what it
    reads, never the whole game (D-86)."""
    st = request.app.state
    game = st.index.load(game_id)
    if game is None:
        raise HTTPException(404, f"game {game_id} not found")
    return game, st.storage.game_dir_with(game_id, *rels)


def _read(path: Path, key: str) -> list[dict]:
    if not path.is_file():
        return []
    doc = json.loads(path.read_text(encoding="utf-8"))
    return doc if isinstance(doc, list) else doc.get(key, [])


def _live_events(gd: Path) -> list[dict]:
    return [e for e in _read(gd / "events.json", "events") if not e.get("dismissed")]


def _frames(gd: Path):
    for chunk in sorted((gd / "tracks").glob("*.json")):
        try:
            yield from json.loads(chunk.read_text()).get("frames", [])
        except (OSError, ValueError):
            continue


def _url(request: Request, game_id: str, rel: str) -> str:
    return request.app.state.storage.url(game_id, rel, str(request.base_url))


def _render(module: str):
    """replay_render.<module>, or 503 where render/ is not installed."""
    import importlib

    try:
        return importlib.import_module(f"replay_render.{module}")
    except ImportError as exc:
        raise HTTPException(503, f"replay_render is not available: {exc}") from exc


def _submit(request: Request, game_id: str, kind: str, stage: str) -> dict:
    """Run one worker stage on this game as an API job (cache-keyed on its inputs). Cloud:
    queued for the hfbox runner, which runs the same stage (remote_runner.run_job)."""
    st = request.app.state
    if st.settings.cloud:
        return st.jobs.submit(kind, game_id, None, params={"stage": stage})
    gd = st.storage.game_dir(game_id)
    try:
        from replay_worker import run
        from replay_worker.stages.discovery import standalone
    except ImportError as exc:
        raise HTTPException(503, f"replay_worker is not available: {exc}") from exc

    def task(job_id: str) -> None:
        run(gd, {}, registry=standalone(stage), stages=[stage], cpu_workers=1,
            progress=lambda s, f: st.jobs.progress(job_id, s, f))  # fmt: skip

    return st.jobs.submit(kind, game_id, task)


def _job(request: Request, game_id: str, kind: str) -> dict | None:
    jobs = [j for j in request.app.state.jobs.for_game(game_id) if j.get("kind") == kind]
    return max(jobs, key=lambda j: j.get("created_at") or 0) if jobs else None


def _render_status(request: Request, game_id: str, kind: str) -> dict:
    """For an output that is not on disk: its newest job's state. A `done` job whose file
    has since been deleted is `missing`, which the POST treats like `none` (re-renders)."""
    job = _job(request, game_id, kind)
    status = job["status"] if job else "none"
    return {"status": "missing" if status == "done" else status, "url": None,
            "job_id": job["id"] if job else None,
            "error": job.get("error") if job else None}  # fmt: skip


# --------------------------------------------------------------------------- hype


def _stored(request: Request, game_id: str, rel: str) -> dict | None:
    """A stage's JSON without mirroring the whole game folder (cloud: one small GET)."""
    st = request.app.state
    if st.index.load(game_id) is None:
        raise HTTPException(404, f"game {game_id} not found")
    path = st.storage.path(game_id, rel)
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


@router.get("/games/{game_id}/hype")
def get_hype(request: Request, game_id: str):
    stored = _stored(request, game_id, HYPE_REL)
    if stored is not None:
        return {**stored, "stored": True}
    gamedata, hype = _render("gamedata"), _render("hype")  # cloud: 503 before any pull
    _, gd = _game(request, game_id, *GAMEDATA, "audio.json", "poses", "media/wide.mp4")
    return {**hype.hype_series(gamedata.load_game(gd)), "stored": False}


# --------------------------------------------------------------------------- rallies


def _rallies(request: Request, game_id: str) -> tuple[dict, Path]:
    try:
        cond = _render("condensed")
    except HTTPException:  # cloud (no replay_render in Lambda): the rendered doc
        stored = _stored(request, game_id, CONDENSED_DOC)
        if not stored:
            raise
        storage = request.app.state.storage
        storage.path(game_id, CONDENSED_REL)  # cloud: mirrors just the rendition's stub
        return stored, storage.games_dir / game_id
    game, gd = _game(request, game_id, "events.json", "plays.json", CONDENSED_DOC, CONDENSED_REL)
    events = _live_events(gd)
    # basketball has no rallies: its condensed game cuts the shots and turnovers
    rallies = cond.rally_list(events, _read(gd / "plays.json", "plays")) or cond.play_list(events)
    doc = cond.browser(rallies, float((game.get("video") or {}).get("duration_s") or 0.0))
    stored = _read_doc(gd / CONDENSED_DOC)
    offsets = {r["event_id"]: r.get("condensed_t") for r in stored.get("rallies", [])}
    for r in rallies:
        r["condensed_t"] = offsets.get(r["event_id"])
    return doc, gd


def _read_doc(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def _condensed_status(request: Request, game_id: str, gd: Path) -> dict:
    if (gd / CONDENSED_REL).is_file():
        return {"status": "done", "url": _url(request, game_id, CONDENSED_REL)}
    return _render_status(request, game_id, "condensed")


@router.get("/games/{game_id}/rallies")
def get_rallies(request: Request, game_id: str):
    doc, gd = _rallies(request, game_id)
    return {**doc, "game_id": game_id, "condensed": _condensed_status(request, game_id, gd)}


@router.get("/games/{game_id}/condensed")
def get_condensed(request: Request, game_id: str):
    _, gd = _game(request, game_id, CONDENSED_DOC, CONDENSED_REL)
    out = _condensed_status(request, game_id, gd)
    stored = _read_doc(gd / CONDENSED_DOC)
    if stored:
        out.update({k: stored.get(k) for k in ("condensed_s", "game_s", "n", "segments")})
    return out


@router.post("/games/{game_id}/condensed", status_code=202)
def post_condensed(request: Request, game_id: str, response: Response):
    doc, gd = _rallies(request, game_id)
    if not doc["n"]:
        raise HTTPException(409, "no rallies, shots or turnovers in this game to condense")
    status = _condensed_status(request, game_id, gd)
    if status["status"] in ("done", "queued", "running"):
        response.status_code = 200
        return status
    job = _submit(request, game_id, "condensed", "condensed")
    return {"status": job["status"], "job_id": job["id"], "url": None}


# --------------------------------------------------------------------------- vertical


def _export(request: Request, game_id: str, gd: Path, vid: str) -> dict:
    spec = _read_doc(gd / VERTICAL_DIR / f"{vid}.json")
    if not spec:
        raise HTTPException(404, f"export {vid} not found")
    rel = f"{VERTICAL_DIR}/{vid}.mp4"
    if (gd / rel).is_file():
        return {**spec, "status": "done", "url": _url(request, game_id, rel)}
    return {**spec, **_render_status(request, game_id, f"vertical:{vid}")}


@router.post("/games/{game_id}/exports/vertical", status_code=202)
def post_vertical(request: Request, game_id: str, body: VerticalIn, response: Response):
    gamedata, vertical = _render("gamedata"), _render("vertical")  # 503 before any pull
    _, gd = _game(request, game_id, *GAMEDATA, "clips.json", VERTICAL_DIR)
    try:
        spec = vertical.resolve(gamedata.load_game(gd), **body.model_dump())
    except KeyError as exc:
        raise HTTPException(404, f"unknown id {exc}") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    vid = vertical.spec_id(spec)
    spec_path = gd / VERTICAL_DIR / f"{vid}.json"
    if not spec_path.is_file():
        request.app.state.storage.write_json(
            game_id, f"{VERTICAL_DIR}/{vid}.json", {**spec, "id": vid, "size": list(vertical.SIZE)}
        )
    out = _export(request, game_id, gd, vid)
    if out["status"] in ("done", "queued", "running"):
        response.status_code = 200
        return out
    job = _submit(request, game_id, f"vertical:{vid}", "vertical")
    return {**out, "status": job["status"], "job_id": job["id"]}


@router.get("/games/{game_id}/exports/vertical")
def list_vertical(request: Request, game_id: str):
    _, gd = _game(request, game_id, VERTICAL_DIR)
    vids = sorted(p.stem for p in (gd / VERTICAL_DIR).glob("v_*.json") if VID.match(p.stem))
    return {"game_id": game_id, "exports": [_export(request, game_id, gd, v) for v in vids]}


@router.get("/games/{game_id}/exports/vertical/{vid}")
def get_vertical(request: Request, game_id: str, vid: str):
    _, gd = _game(request, game_id, VERTICAL_DIR)
    if not VID.match(vid):
        raise HTTPException(404, f"export {vid} not found")
    return _export(request, game_id, gd, vid)


# --------------------------------------------------------------------------- reel


class ReelIn(BaseModel):
    aspect: Literal["16:9", "9:16"] = "16:9"


def _reel(request: Request, game_id: str, rid: str) -> dict:
    storage = request.app.state.storage
    spec_p = storage.path(game_id, f"{REEL_DIR}/{rid}.json") if RID.match(rid) else None
    if spec_p is None or not spec_p.is_file():
        raise HTTPException(404, f"reel {rid} not found")
    spec = json.loads(spec_p.read_text(encoding="utf-8"))
    rel = f"{REEL_DIR}/{rid}.mp4"
    if storage.path(game_id, rel).is_file():
        plan = _read_doc(storage.path(game_id, f"{REEL_DIR}/{rid}.plan.json"))
        return {**spec, "status": "done", "url": _url(request, game_id, rel),
                "duration_s": plan.get("duration_s"), "segments": plan.get("segments", [])}  # fmt: skip
    return {**spec, **_render_status(request, game_id, f"reel:{rid}")}


@router.post("/games/{game_id}/exports/reel", status_code=202)
def post_reel(request: Request, game_id: str, body: ReelIn, response: Response):
    """The game's highlight reel (top plays + the user's clips) as one MP4. The id hashes
    the aspect and the files the plan is made from, so asking again before anything
    changed is the same reel (200), and a new clip or an edit makes a new one (202)."""
    st = request.app.state
    if st.index.load(game_id) is None:
        raise HTTPException(404, f"game {game_id} not found")
    h = hashlib.sha256(body.aspect.encode())
    for rel in REEL_INPUTS:
        p = st.storage.path(game_id, rel)
        h.update(rel.encode() + b"\0" + (p.read_bytes() if p.is_file() else b"") + b"\0")
    rid = "r_" + h.hexdigest()[:12]
    if not st.storage.path(game_id, f"{REEL_DIR}/{rid}.json").is_file():
        st.storage.write_json(game_id, f"{REEL_DIR}/{rid}.json",
                              {"id": rid, "aspect": body.aspect, "created_at": time.time()})  # fmt: skip
    out = _reel(request, game_id, rid)
    if out["status"] in ("done", "queued", "running"):
        response.status_code = 200
        return out
    job = _submit(request, game_id, f"reel:{rid}", "reel")
    return {**out, "status": job["status"], "job_id": job["id"]}


@router.get("/games/{game_id}/exports/reel")
def list_reels(request: Request, game_id: str):
    """Every reel of this game, newest first."""
    st = request.app.state
    if st.index.load(game_id) is None:
        raise HTTPException(404, f"game {game_id} not found")
    d = st.storage.path(game_id, REEL_DIR)
    rids = [p.stem for p in d.glob("r_*.json") if RID.match(p.stem)]
    reels = [_reel(request, game_id, r) for r in rids]
    reels.sort(key=lambda r: -(r.get("created_at") or 0))
    return {"game_id": game_id, "reels": reels}


@router.get("/games/{game_id}/exports/reel/{rid}")
def get_reel(request: Request, game_id: str, rid: str):
    if request.app.state.index.load(game_id) is None:
        raise HTTPException(404, f"game {game_id} not found")
    return _reel(request, game_id, rid)


# --------------------------------------------------------------------------- review


@router.get("/games/{game_id}/review/queue")
def review_queue(request: Request, game_id: str):
    game, gd = _game(request, game_id, "events.json", "tracks")
    questions = stats_mod.review_queue(game, _live_events(gd), _frames(gd))
    return {"game_id": game_id, "label": "auto-detected", "questions": questions}
