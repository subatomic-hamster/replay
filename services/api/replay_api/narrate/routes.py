"""M7 endpoints (additive): commentary per game / play, advice per player, semantic search.

The free-text → structured-filter LLM path is the existing `POST /games/{id}/query` with
`REPLAY_QUERY=llm` (providers/query.py). Files the worker's narrate stages write:
`commentary/script.json` (+ `narration.wav`, `<play_id>.wav`) and `embeddings/`. Without
them, commentary and advice are generated on request from the JSON (templates; the LLM
paraphrase with `?llm=true`), and search answers 409.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .. import pipeline_adapter as adapter
from .. import stats as stats_mod
from ..providers import NotConfiguredError
from ..providers.query import get_query_engine, merged_vocab
from . import advice as A
from . import commentary as C
from . import search as S

router = APIRouter()
SCRIPT_REL = "commentary/script.json"


class SearchIn(BaseModel):
    text: str = Field(min_length=1, max_length=300)
    k: int = Field(default=5, ge=1, le=50)


def _docs(request: Request, game_id: str):
    st = request.app.state
    game = st.index.load(game_id)
    if game is None:
        raise HTTPException(404, f"game {game_id} not found")
    # what load_docs reads, not the whole game (D-86)
    gd = st.storage.game_dir_with(game_id, "game.json", "events.json", "plays.json", "score.json")
    if not (gd / "game.json").is_file():
        return game, [], [], []
    _, events, plays, score = C.load_docs(gd)
    return game, events, plays, score


def _media(request: Request, game_id: str, rel: str) -> str | None:
    st = request.app.state
    if not st.storage.path(game_id, rel).is_file():
        return None
    return st.storage.url(game_id, rel, str(request.base_url))


def _script(request: Request, game_id: str, llm: bool, only: str | None = None) -> dict:
    game, events, plays, score = _docs(request, game_id)
    # the folder once: the script and every play's audio below (one LIST, not one a play)
    stored = request.app.state.storage.game_dir_with(game_id, "commentary") / SCRIPT_REL
    if stored.is_file() and not llm:
        doc = json.loads(stored.read_text(encoding="utf-8"))
        doc["stored"] = True
    else:
        model = request.app.state.llm if llm else None
        doc = C.game_script(game, events, plays, score, llm=model, only=only)
        doc["stored"] = False
    doc["narration_url"] = _media(request, game_id, "commentary/narration.wav")
    for s in doc["plays"]:
        s["text_url"] = f"/games/{game_id}/plays/{s['play_id']}/commentary"
        s["audio_url"] = _media(request, game_id, f"commentary/{s['play_id']}.wav")
    return doc


@router.get("/games/{game_id}/commentary")
def game_commentary(request: Request, game_id: str, llm: bool = False):
    doc = _script(request, game_id, llm)
    for s in doc["plays"]:
        s.pop("facts", None)  # per-play endpoint keeps them
    return doc


@router.get("/games/{game_id}/plays/{play_id}/commentary")
def play_commentary(request: Request, game_id: str, play_id: str, llm: bool = False):
    doc = _script(request, game_id, llm, only=play_id)
    hit = next((s for s in doc["plays"] if s["play_id"] == play_id), None)
    if hit is None:
        raise HTTPException(404, f"play {play_id} not found")
    return {"schema": C.SCHEMA, "game_id": game_id, **hit}


def _frames(request: Request, game_id: str):
    for chunk in sorted(request.app.state.storage.path(game_id, "tracks").glob("*.json")):
        try:
            yield from json.loads(chunk.read_text()).get("frames", [])
        except (OSError, ValueError):
            continue


@router.get("/games/{game_id}/players/{player_id}/advice")
def player_advice(request: Request, game_id: str, player_id: str, llm: bool = False):
    game, events, plays, _ = _docs(request, game_id)
    if player_id not in {p["id"] for p in game.get("players") or []}:
        raise HTTPException(404, f"player {player_id} not found")
    profile = adapter.get_profile(game.get("sport", ""), (game.get("court") or {}).get("variant"))
    stats = stats_mod.compute(game, events, _frames(request, game_id), profile)
    model = request.app.state.llm if llm else None
    return A.player_advice(game, events, plays, stats, player_id, llm=model)


@router.post("/games/{game_id}/search")
def search(request: Request, game_id: str, body: SearchIn):
    game, events, _, _ = _docs(request, game_id)
    st = request.app.state
    index_path = Path(st.storage.path(game_id, S.INDEX))
    if not index_path.is_file():
        raise HTTPException(409, "no embeddings yet: run the worker's `embeddings` stage")
    index = json.loads(index_path.read_text(encoding="utf-8"))
    try:
        q = st.embeddings.embed_texts([body.text])[0]
    except NotConfiguredError as exc:
        raise HTTPException(503, str(exc)) from exc
    profile = adapter.get_profile(game.get("sport", "")) or {}
    engine = get_query_engine(st.settings.query, merged_vocab(profile.get("query_vocab")))
    filt = engine.query(body.text, game, events)
    results = S.rank(st.storage.game_dir_with(game_id, "embeddings"), index, q,
                     filt.get("event_ids", []), body.k,
                     query_text=body.text)  # fmt: skip
    return {
        "query": body.text,
        "model": index.get("model"),
        "interpretation": filt["interpretation"],
        "filter_source": filt.get("source", "rules"),
        "results": results,
    }
