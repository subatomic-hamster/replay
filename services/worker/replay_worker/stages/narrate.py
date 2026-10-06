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
registers them, plus voice / LLM switch and whether a TTS model is configured (without
one the script is written text-only, `tts.skipped` saying why); embeddings is one task
over the plays file and the wide video that embeds every play in one model load. A
replaced plays.json recomputes every play (coarse).
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
        try:
            script["tts"] = C.narrate(script, tts, out, duration_s=dur,
                                      voice=ctx.cfg.get("commentary_voice"))  # fmt: skip
            script["tts"]["runner"] = getattr(tts, "last", {})
        except providers.NotConfiguredError as exc:
            # no TTS model here (REPLAY_MODEL_VENVS unset): captions only, said so
            script["tts"] = {"skipped": str(exc)}
    (out / "script.json").write_text(json.dumps(script, indent=1), encoding="utf-8")


def _tts_ready(cfg: dict) -> bool:
    """Part of the commentary key: a text-only script must not stay cached once a TTS
    model is configured."""
    from replay_api.providers import _runner

    return _runner.python_for("tts") is not None


def run_embeddings(ctx: Ctx, item: str | None) -> None:
    """Every play in one model-runner process (one model load per stage run, not per
    play: the per-play fan-out reloaded SigLIP ~10 s each and keyed every play on the
    same files anyway)."""
    from replay_api import providers
    from replay_api.narrate import commentary as C
    from replay_api.narrate import search as S

    game, events, plays, score = _docs(ctx)
    out = ctx.game_dir / "embeddings"
    out.mkdir(parents=True, exist_ok=True)
    items = [(p, S.play_text(game, p, events, score), out / f"{S.safe_id(p['id'])}.npy")
             for p in C.game_plays(plays, events)]  # fmt: skip
    if items:
        S.embed_plays(providers.create("embeddings"), ctx.game_dir / P.WIDE_REL, items)


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
        key_extra=_tts_ready,
        default=False,
    ),
    Stage(
        "embeddings",
        VERSION,
        run_embeddings,
        inputs=("events.json", "game.json", P.WIDE_REL, *OPTIONAL),
        # the whole dir: search_index (uncached, after this) rewrites its index.json
        outputs=("embeddings",),
        after=("game",),
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
