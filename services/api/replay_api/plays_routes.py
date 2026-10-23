"""M4/M5 routes: plays, "Replay, clip that" triggers, clips and the score.

The pipeline writes plays.json / triggers.json / clips.json / score.json (courtcam
`stage_plays`); these routes read them and add the user's side: a tap from the phone
companion (`POST /triggers`), a trimmed clip (`PATCH /clips/{id}`) and a score
correction (`POST /score`). Everything the user adds is `source: "user"`, recorded in
edits.json and applied to the same files, so it survives worker re-runs (D-61).
"""

from __future__ import annotations

import json
import secrets
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from . import edits
from . import moments as moments_mod
from . import pipeline_adapter as adapter

PLAYS_REL, TRIGGERS_REL, CLIPS_REL, SCORE_REL = (
    "plays.json",
    "triggers.json",
    "clips.json",
    "score.json",
)
NOTES_REL = "notes.json"  # the uploader's play log (D-90); = moments.NOTES_REL
NOTES_MAX_BYTES = 1_000_000
HYPE_REL = "hype.json"  # the `hype` stage's (= discovery_routes.HYPE_REL)
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


class ScoringIn(BaseModel):
    mode: Literal["standard", "pickup"]  # 2s and 3s, or 1s and 2s (adapter.with_scoring)


class BestPlayIn(BaseModel):
    """The user's best play: a window, the time to mark, and the moment it is (optional)."""

    t_start: float = Field(ge=0)
    t_end: float = Field(gt=0)
    t: float = Field(ge=0)
    moment_id: str | None = Field(default=None, max_length=64)


class ScoreIn(BaseModel):
    t: float = Field(ge=0)
    scores: tuple[int, int]
    event_id: str | None = None


def _load(storage, game_id: str, rel: str) -> list[dict]:
    p = storage.path(game_id, rel)
    if not p.is_file():
        return []
    return json.loads(p.read_text()).get(SCHEMAS[rel][1], [])


def _user_scores(storage, game_id: str) -> list[dict]:
    """The user's score entries: edits.json, else (a game corrected before D-61) the
    `source: user` entries still in score.json."""
    ov = edits.load(storage.game_dir_with(game_id, edits.REL))
    if "score" in ov:
        return ov["score"]
    return [s for s in _load(storage, game_id, SCORE_REL) if s.get("source") == "user"]


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
        gd = storage.game_dir_with(game_id, edits.REL, TRIGGERS_REL, PLAYS_REL, CLIPS_REL)
        if play_id is not None:
            trigger["play_id"], trigger["clip_id"] = play_id, clip["id"]
            bare = {k: v for k, v in trigger.items() if k not in ("play_id", "clip_id")}
            edits.patch(gd, PLAYS_REL, play_id, {"trigger": bare})
            edits.add(gd, CLIPS_REL, clip)
        edits.add(gd, TRIGGERS_REL, trigger)  # D-61: survives worker re-runs
        edits.apply(gd, (TRIGGERS_REL, PLAYS_REL, CLIPS_REL))
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
            c.setdefault("edited", False)  # additive: true once a user trims it
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
        # `edited` says a person trimmed it whoever made it; `source: user` stays for
        # clients that read it as "edited" (D-61)
        fields = {"t_start": round(body.t_start, 3), "t_end": round(body.t_end, 3),
                  "source": "user", "edited": True}  # fmt: skip
        gd = storage.game_dir_with(game_id, edits.REL, CLIPS_REL)
        edits.patch(gd, CLIPS_REL, clip_id, fields)
        edits.apply(gd, (CLIPS_REL,))
        clip.update(fields)
        return clip

    @app.get("/games/{game_id}/score")
    def get_score(request: Request, game_id: str):
        """Recomputed from the current events (corrections to makes and points count) plus
        the user's own score entries."""
        storage = ctx(request).storage
        game = game_or_404(request, game_id)
        user = _user_scores(storage, game_id)
        ov = edits.load(storage.game_dir_with(game_id, edits.REL))
        events = adapter.with_scoring(live_events(events_of(storage, game_id)), ov)
        score = adapter.score_timeline(events, user, game.get("sport"), adapter.user_teams(ov))
        return {
            "schema": "replay.score.v1",
            "score": score,
            "final": score[-1]["scores"] if score else [0, 0],
            "scoring": ov.get("scoring") or "standard",
        }

    @app.put("/games/{game_id}/scoring")
    def put_scoring(request: Request, game_id: str, body: ScoringIn):
        """What a basket is worth in this game: "standard" (2s and 3s) or "pickup" (1s and
        2s). Kept in edits.json; the score and stats are recounted at read time (and
        score.json rewritten for its file readers), no re-run."""
        storage = ctx(request).storage
        game_or_404(request, game_id)
        gd = storage.game_dir_with(game_id, edits.REL, SCORE_REL, "events.json")
        edits.record(gd, lambda ov: ov.update(scoring=body.mode))
        edits.apply(gd, (SCORE_REL,))
        return {"scoring": body.mode}

    @app.post("/games/{game_id}/score", status_code=201)
    def post_score(request: Request, game_id: str, body: ScoreIn):
        """Set the score from time `t` on (a missed basket, a disputed point)."""
        storage = ctx(request).storage
        game_or_404(request, game_id)
        if min(body.scores) < 0:
            raise HTTPException(400, "scores cannot be negative")
        entry = {"t": round(body.t, 3), "scores": list(body.scores), "event_id": body.event_id,
                 "source": "user"}  # fmt: skip
        user = sorted([*_user_scores(storage, game_id), entry], key=lambda s: s["t"])
        # the score file is recomputed from the events
        gd = storage.game_dir_with(game_id, edits.REL, SCORE_REL, "events.json")
        edits.record(gd, lambda ov: ov.update(score=user))  # D-61: survives re-runs
        # the file stays the whole timeline (the broadcast renderer reads it as is)
        edits.apply(gd, (SCORE_REL,))
        return entry

    # ------------------------------------------------------------ best play

    def _best(storage, game_id: str, game: dict) -> dict:
        """Computed at read time from the live moments, hype.json and the user's pick in
        edits.json, so a rename, a dismissal or a new pick shows without a re-run."""
        notes_p = storage.path(game_id, NOTES_REL)
        rows = moments_mod.all_moments(
            events_of(storage, game_id), game, _load(storage, game_id, TRIGGERS_REL),
            _load(storage, game_id, CLIPS_REL),
            json.loads(notes_p.read_text()) if notes_p.is_file() else None,
        )  # fmt: skip
        hype_p = storage.path(game_id, HYPE_REL)
        hype = json.loads(hype_p.read_text()) if hype_p.is_file() else None
        user = edits.load(storage.game_dir_with(game_id, edits.REL)).get("best_play")
        duration = (game.get("video") or {}).get("duration_s")
        return {"best_play": moments_mod.best_play(rows, hype, duration, user)}

    @app.get("/games/{game_id}/best-play")
    def get_best_play(request: Request, game_id: str):
        """The game's best play: the user's pick, else the game winner, else the top hype
        play; `source` says which. `best_play` is null when nothing qualifies."""
        game = game_or_404(request, game_id)
        return _best(ctx(request).storage, game_id, game)

    @app.put("/games/{game_id}/best-play")
    def put_best_play(request: Request, game_id: str, body: BestPlayIn):
        """ "Make this the best play" (phone): one per game, replacing an earlier pick.
        Recorded in edits.json, so it survives worker re-runs (D-61)."""
        storage = ctx(request).storage
        game = game_or_404(request, game_id)
        duration = (game.get("video") or {}).get("duration_s")
        if body.t_end <= body.t_start or (duration and body.t_end > duration + 1e-6):
            raise HTTPException(400, "need 0 <= t_start < t_end <= the video's duration")
        if not body.t_start <= body.t <= body.t_end:
            raise HTTPException(400, "t must be inside t_start..t_end")
        pick = {"t": round(body.t, 3), "t_start": round(body.t_start, 3),
                "t_end": round(body.t_end, 3), "moment_id": body.moment_id}  # fmt: skip
        gd = storage.game_dir_with(game_id, edits.REL)
        edits.record(gd, lambda ov: ov.update(best_play=pick))
        return _best(storage, game_id, game)

    @app.delete("/games/{game_id}/best-play")
    def delete_best_play(request: Request, game_id: str):
        """Drop the user's pick: the automatic rule chooses again."""
        storage = ctx(request).storage
        game = game_or_404(request, game_id)
        gd = storage.game_dir_with(game_id, edits.REL)
        edits.record(gd, lambda ov: ov.pop("best_play", None))
        return _best(storage, game_id, game)

    @app.post("/games/{game_id}/notes", status_code=201)
    async def post_notes(request: Request, game_id: str):
        """The uploader's own play log (CSV or JSON as the body, docs/playlog.md) as the
        game's notes.json, replacing earlier notes. Shown as "Your note" moments; never
        merged into events, score or stats (D-90). X-Replay-Key only (not a phone route)."""
        storage = ctx(request).storage
        game = game_or_404(request, game_id)
        raw = await request.body()
        if len(raw) > NOTES_MAX_BYTES:
            raise HTTPException(413, f"a play log is at most {NOTES_MAX_BYTES} bytes")
        try:
            doc = adapter.user_notes(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc
        duration = (game.get("video") or {}).get("duration_s")
        late = [e["t"] for e in doc["entries"] if duration and e["t"] > duration]
        if late:
            raise HTTPException(400, f"t {late[0]} is past the end of the video ({duration} s)")
        storage.write_json(game_id, NOTES_REL, doc)
        return {"notes": len(doc["entries"]), "label": doc["label"]}

    @app.get("/games/{game_id}/notes")
    def get_notes(request: Request, game_id: str):
        """The uploader's notes as loaded (`replay.playlog.v1`), or an empty log."""
        game_or_404(request, game_id)
        p = ctx(request).storage.path(game_id, NOTES_REL)
        return json.loads(p.read_text()) if p.is_file() else {
            "schema": "replay.playlog.v1", "use": "notes", "entries": []}  # fmt: skip
