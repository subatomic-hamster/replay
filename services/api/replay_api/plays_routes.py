"""M4/M5 routes: plays, "Replay, clip that" triggers, clips and the score.

The pipeline writes plays.json / triggers.json / clips.json / score.json (courtcam
`stage_plays`); these routes read them and add the user's side: a tap from the phone
companion (`POST /triggers`), a trimmed clip (`PATCH /clips/{id}`) and a score
correction (`POST /score`). Everything the user adds is `source: "user"` and survives
in the same files.
"""

from __future__ import annotations

import json
import secrets

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from . import pipeline_adapter as adapter

PLAYS_REL, TRIGGERS_REL, CLIPS_REL, SCORE_REL = (
    "plays.json",
    "triggers.json",
    "clips.json",
    "score.json",
)
SCHEMAS = {
    PLAYS_REL: ("replay.plays.v1", "plays"),
    TRIGGERS_REL: ("replay.triggers.v1", "triggers"),
    CLIPS_REL: ("replay.clips.v1", "clips"),
    SCORE_REL: ("replay.score.v1", "score"),
}


class TapIn(BaseModel):
    t: float = Field(ge=0)
    by_player_id: str | None = None


class ClipTrim(BaseModel):
    t_start: float = Field(ge=0)
    t_end: float = Field(gt=0)


class ScoreIn(BaseModel):
    t: float = Field(ge=0)
    scores: tuple[int, int]
    event_id: str | None = None


def _load(storage, game_id: str, rel: str) -> list[dict]:
    p = storage.path(game_id, rel)
    if not p.is_file():
        return []
    return json.loads(p.read_text()).get(SCHEMAS[rel][1], [])


def _save(storage, game_id: str, rel: str, items: list[dict]) -> None:
    schema, key = SCHEMAS[rel]
    storage.write_json(game_id, rel, {"schema": schema, key: items})


def _roster(game: dict) -> dict[str, str]:
    return {p["name"]: p["id"] for p in game.get("players", []) if p.get("name")}


def register(app: FastAPI, game_or_404, events_of, live_events) -> None:
    """Add the routes. The helpers come from main.py so there is one way to load a game."""

    def ctx(request: Request):
        return request.app.state

    @app.get("/games/{game_id}/plays")
    def get_plays(request: Request, game_id: str, grammar: str | None = None):
        game_or_404(request, game_id)
        plays = _load(ctx(request).storage, game_id, PLAYS_REL)
        if grammar:
            plays = [p for p in plays if p.get("grammar") == grammar]
        return {"schema": "replay.plays.v1", "plays": plays}

    @app.get("/games/{game_id}/triggers")
    def get_triggers(request: Request, game_id: str):
        """The triggers, each with the play and clip it resolved to (the pipeline's
        triggers stage runs before plays exist, so its file leaves those empty)."""
        storage = ctx(request).storage
        game_or_404(request, game_id)
        by_trigger = {c.get("trigger_id"): c for c in _load(storage, game_id, CLIPS_REL)}
        triggers = _load(storage, game_id, TRIGGERS_REL)
        for t in triggers:
            c = by_trigger.get(t["id"])
            if c is not None:
                t["play_id"], t["clip_id"] = c["play_id"], c["id"]
        return {"schema": "replay.triggers.v1", "triggers": triggers}

    @app.post("/games/{game_id}/triggers", status_code=201)
    def post_trigger(request: Request, game_id: str, body: TapIn):
        """A tap from the phone: resolve it to the play that just ended, cut the clip."""
        storage = ctx(request).storage
        game = game_or_404(request, game_id)
        duration = (game.get("video") or {}).get("duration_s")
        if duration and body.t > duration:
            raise HTTPException(400, f"t {body.t} is past the end of the video ({duration} s)")
        if body.by_player_id and body.by_player_id not in {
            p["id"] for p in game.get("players", [])
        }:
            raise HTTPException(404, f"player {body.by_player_id} not found")
        plays = _load(storage, game_id, PLAYS_REL)
        trigger = {
            "id": "tr_u" + secrets.token_hex(4),
            "type": "tap",
            "t": round(body.t, 3),
            "by_player_id": body.by_player_id,
            "confidence": 1.0,
            "source": "user",
            "play_id": None,
            "clip_id": None,
        }
        play_id, clip = adapter.resolve_trigger(game["sport"], trigger, plays, duration)
        if play_id is not None:
            trigger["play_id"], trigger["clip_id"] = play_id, clip["id"]
            for p in plays:
                if p["id"] == play_id:
                    p["trigger"] = {
                        k: v for k, v in trigger.items() if k not in ("play_id", "clip_id")
                    }
            _save(storage, game_id, PLAYS_REL, plays)
            _save(storage, game_id, CLIPS_REL, [*_load(storage, game_id, CLIPS_REL), clip])
        triggers = _load(storage, game_id, TRIGGERS_REL)
        _save(storage, game_id, TRIGGERS_REL, sorted([*triggers, trigger], key=lambda x: x["t"]))
        return {"trigger": trigger, "clip": clip}

    @app.get("/games/{game_id}/clips")
    def get_clips(request: Request, game_id: str, player_id: str | None = None):
        """Every clip; a voice clip's subject is re-read from its transcript against the
        current roster (players are named after the run)."""
        storage = ctx(request).storage
        game = game_or_404(request, game_id)
        roster = _roster(game)
        trig = {t["id"]: t for t in _load(storage, game_id, TRIGGERS_REL)}
        clips = _load(storage, game_id, CLIPS_REL)
        for c in clips:
            t = trig.get(c.get("trigger_id") or "")
            if t and t.get("type") == "voice" and roster:
                subject = adapter.trigger_subject(game["sport"], t.get("transcript"), roster)
                if subject:
                    a = c.setdefault("attribution", {})
                    a["subject_player_id"] = subject
                    a["owner_player_id"] = a.get("by_player_id") or subject
        if player_id:  # "my clips": I made the gesture / was named / took part
            clips = [
                c for c in clips
                if player_id in (c.get("attribution") or {}).values()
                or player_id in c.get("participants", [])
            ]  # fmt: skip
        return {"schema": "replay.clips.v1", "clips": clips}

    @app.patch("/games/{game_id}/clips/{clip_id}")
    def trim_clip(request: Request, game_id: str, clip_id: str, body: ClipTrim):
        storage = ctx(request).storage
        game = game_or_404(request, game_id)
        duration = (game.get("video") or {}).get("duration_s")
        if body.t_end <= body.t_start or (duration and body.t_end > duration + 1e-6):
            raise HTTPException(400, "need 0 <= t_start < t_end <= the video's duration")
        clips = _load(storage, game_id, CLIPS_REL)
        clip = next((c for c in clips if c["id"] == clip_id), None)
        if clip is None:
            raise HTTPException(404, f"clip {clip_id} not found")
        clip.update(t_start=round(body.t_start, 3), t_end=round(body.t_end, 3), source="user")
        _save(storage, game_id, CLIPS_REL, clips)
        return clip

    @app.get("/games/{game_id}/score")
    def get_score(request: Request, game_id: str):
        """Recomputed from the current events (corrections to makes and points count) plus
        the user's own score entries."""
        storage = ctx(request).storage
        game_or_404(request, game_id)
        user = [s for s in _load(storage, game_id, SCORE_REL) if s.get("source") == "user"]
        score = adapter.score_timeline(live_events(events_of(storage, game_id)), user)
        return {
            "schema": "replay.score.v1",
            "score": score,
            "final": score[-1]["scores"] if score else [0, 0],
        }

    @app.post("/games/{game_id}/score", status_code=201)
    def post_score(request: Request, game_id: str, body: ScoreIn):
        """Set the score from time `t` on (a missed basket, a disputed point)."""
        storage = ctx(request).storage
        game_or_404(request, game_id)
        if min(body.scores) < 0:
            raise HTTPException(400, "scores cannot be negative")
        entry = {"t": round(body.t, 3), "scores": list(body.scores), "event_id": body.event_id,
                 "source": "user"}  # fmt: skip
        user = [s for s in _load(storage, game_id, SCORE_REL) if s.get("source") == "user"]
        user = sorted([*user, entry], key=lambda s: s["t"])
        # the file stays the whole timeline (the broadcast renderer reads it as is)
        score = adapter.score_timeline(live_events(events_of(storage, game_id)), user)
        _save(storage, game_id, SCORE_REL, score)
        return entry
