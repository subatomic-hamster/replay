"""M7 stages: `commentary` (script + narration WAV) and `embeddings` -> `search_index`.

They call the API package's `replay_api.narrate` (services/api on PYTHONPATH, as on the
box) and its local providers (Kokoro TTS, llama.cpp LLM, SigLIP embeddings), which run
in their own venvs through the model runner and take the GPU lock themselves only while a
model runs — so these stages are `cpu` here (the DAG must not hold the lock around a
subprocess that takes it too). None is in the default DAG: `--stages commentary`,
`--stages search_index`.

Broadcast hand-off: run the broadcast stage with `narration=<game>/commentary/narration.wav`
in the config; replay_render's mixer ducks the game audio under it.

Cache keys: commentary hashes events, game.json (names), plays/score when the plays stage
registers them, plus voice / LLM switch; embeddings fan out one task per play over the
plays file and the wide video. A replaced plays.json recomputes every play (coarse).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

from courtcam import pipeline as P

from ..dag import Ctx, Stage
from . import courtcam as cc


def _code_hash() -> str:
    """replay_api.narrate + the providers' sources, found without importing replay_api."""
    spec = importlib.util.find_spec("replay_api")
    root = (
        Path(spec.origin).parent
        if spec and spec.origin
        else Path(__file__).resolve().parents[3] / "api" / "replay_api"
    )
    h = hashlib.sha256(Path(__file__).read_bytes())
    for f in sorted([*root.glob("narrate/*.py"), *root.glob("providers/*.py")]):
        h.update(f.name.encode() + b"\0" + f.read_bytes())
    return h.hexdigest()[:12]


VERSION = "1+" + _code_hash()
OUT = "commentary"
_CC_OUTPUTS = {o for s in cc.STAGES for o in s.outputs}
OPTIONAL = tuple(f for f in ("plays.json", "score.json") if f in _CC_OUTPUTS)


def _docs(ctx: Ctx):
    from replay_api.narrate import commentary as C

    return C.load_docs(ctx.game_dir)


def run_commentary(ctx: Ctx, item: str | None) -> None:
    from replay_api import providers
    from replay_api.narrate import commentary as C

    game, events, plays, score = _docs(ctx)
    llm = providers.create("llm") if ctx.cfg.get("commentary_llm") else None
    script = C.game_script(game, events, plays, score, llm=llm)
    out = ctx.game_dir / OUT
    out.mkdir(parents=True, exist_ok=True)
    if ctx.cfg.get("commentary_tts", True):
        tts = providers.create("tts")
        dur = float((game.get("video") or {}).get("duration_s") or 0.0)
        script["tts"] = C.narrate(script, tts, out, duration_s=dur,
                                  voice=ctx.cfg.get("commentary_voice"))  # fmt: skip
        script["tts"]["runner"] = getattr(tts, "last", {})
    (out / "script.json").write_text(json.dumps(script, indent=1), encoding="utf-8")


def _play_ids(ctx: Ctx) -> list[str]:
    from replay_api.narrate import commentary as C
    from replay_api.narrate import search as S

    _, events, plays, _ = _docs(ctx)
    return [S.safe_id(p["id"]) for p in C.game_plays(plays, events)]


def run_embeddings(ctx: Ctx, item: str | None) -> None:
    from replay_api import providers
    from replay_api.narrate import commentary as C
    from replay_api.narrate import search as S

    game, events, plays, score = _docs(ctx)
    play = next(p for p in C.game_plays(plays, events) if S.safe_id(p["id"]) == item)
    text = S.play_text(game, play, events, score)
    out = ctx.game_dir / "embeddings" / f"{item}.npy"
    S.embed_play(providers.create("embeddings"), ctx.game_dir / P.WIDE_REL, play, text, out)


def run_index(ctx: Ctx, item: str | None) -> None:
    from replay_api import providers
    from replay_api.narrate import commentary as C
    from replay_api.narrate import search as S

    game, events, plays, score = _docs(ctx)
    ps = C.game_plays(plays, events)
    texts = {p["id"]: S.play_text(game, p, events, score) for p in ps}
    S.write_index(ctx.game_dir, ps, texts, getattr(providers.implementation("embeddings"),
                                                  "name", "embeddings"))  # fmt: skip


STAGES = [
    Stage(
        "commentary",
        VERSION,
        run_commentary,
        inputs=("events.json", "game.json", *OPTIONAL),
        outputs=(OUT,),
        params=("commentary_voice", "commentary_llm", "commentary_tts"),
        after=("game",),
        default=False,
    ),
    Stage(
        "embeddings",
        VERSION,
        run_embeddings,
        inputs=("events.json", "game.json", P.WIDE_REL, *OPTIONAL),
        outputs=("embeddings/{item}.npy",),
        after=("game",),
        fanout=_play_ids,
        default=False,
    ),
    Stage(
        "search_index",
        VERSION,
        run_index,
        inputs=("events.json", "game.json", *OPTIONAL),
        outputs=("embeddings/index.json",),
        after=("embeddings",),
        default=False,
        cache=False,  # cheap; its inputs include the npy files it lists
    ),
]
