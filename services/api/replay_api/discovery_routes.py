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
    GET  /games/{id}/review/queue            questions answered with existing PATCH routes
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from . import stats as stats_mod

router = APIRouter()
HYPE_REL = "hype.json"
CONDENSED_REL = "renditions/condensed.mp4"
CONDENSED_DOC = "condensed.json"
VERTICAL_DIR = "exports/vertical"
VID = re.compile(r"^v_[0-9a-f]{12}$")


class VerticalIn(BaseModel):
    clip_id: str | None = None
    play_id: str | None = None
    event_id: str | None = None
    t_start: float | None = Field(default=None, ge=0)
    t_end: float | None = Field(default=None, gt=0)
    player_id: str | None = None


def _game(request: Request, game_id: str) -> tuple[dict, Path]:
    st = request.app.state
    game = st.index.load(game_id)
    if game is None:
        raise HTTPException(404, f"game {game_id} not found")
    return game, st.storage.game_dir(game_id)


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
    """Run one worker stage on this game as an API job (cache-keyed on its inputs)."""
    st = request.app.state
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


# --------------------------------------------------------------------------- hype


@router.get("/games/{game_id}/hype")
def get_hype(request: Request, game_id: str):
    _, gd = _game(request, game_id)
    if (gd / HYPE_REL).is_file():
        return {**json.loads((gd / HYPE_REL).read_text(encoding="utf-8")), "stored": True}
    gamedata, hype = _render("gamedata"), _render("hype")
    return {**hype.hype_series(gamedata.load_game(gd)), "stored": False}


# --------------------------------------------------------------------------- rallies


def _rallies(request: Request, game_id: str) -> tuple[dict, Path]:
    game, gd = _game(request, game_id)
    cond = _render("condensed")
    rallies = cond.rally_list(_live_events(gd), _read(gd / "plays.json", "plays"))
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
    job = _job(request, game_id, "condensed")
    return {"status": job["status"] if job else "none", "url": None,
            "job_id": job["id"] if job else None,
            "error": job.get("error") if job else None}  # fmt: skip


@router.get("/games/{game_id}/rallies")
def get_rallies(request: Request, game_id: str):
    doc, gd = _rallies(request, game_id)
    return {**doc, "game_id": game_id, "condensed": _condensed_status(request, game_id, gd)}


@router.get("/games/{game_id}/condensed")
def get_condensed(request: Request, game_id: str):
    _, gd = _game(request, game_id)
    out = _condensed_status(request, game_id, gd)
    stored = _read_doc(gd / CONDENSED_DOC)
    if stored:
        out.update({k: stored.get(k) for k in ("condensed_s", "game_s", "n", "segments")})
    return out


@router.post("/games/{game_id}/condensed", status_code=202)
def post_condensed(request: Request, game_id: str, response: Response):
    doc, gd = _rallies(request, game_id)
    if not doc["n"]:
        raise HTTPException(409, "no rallies in this game: the condensed game is for net sports")
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
    job = _job(request, game_id, f"vertical:{vid}")
    return {**spec, "status": job["status"] if job else "none", "url": None,
            "job_id": job["id"] if job else None,
            "error": job.get("error") if job else None}  # fmt: skip


@router.post("/games/{game_id}/exports/vertical", status_code=202)
def post_vertical(request: Request, game_id: str, body: VerticalIn, response: Response):
    _, gd = _game(request, game_id)
    gamedata, vertical = _render("gamedata"), _render("vertical")
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
    _, gd = _game(request, game_id)
    vids = sorted(p.stem for p in (gd / VERTICAL_DIR).glob("v_*.json") if VID.match(p.stem))
    return {"game_id": game_id, "exports": [_export(request, game_id, gd, v) for v in vids]}


@router.get("/games/{game_id}/exports/vertical/{vid}")
def get_vertical(request: Request, game_id: str, vid: str):
    _, gd = _game(request, game_id)
    if not VID.match(vid):
        raise HTTPException(404, f"export {vid} not found")
    return _export(request, game_id, gd, vid)


# --------------------------------------------------------------------------- review


@router.get("/games/{game_id}/review/queue")
def review_queue(request: Request, game_id: str):
    game, gd = _game(request, game_id)
    questions = stats_mod.review_queue(game, _live_events(gd), _frames(gd))
    return {"game_id": game_id, "label": "auto-detected", "questions": questions}
