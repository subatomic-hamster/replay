"""Broadcast mode (M6): `director` -> cuts.json, `broadcast` -> renditions/broadcast.mp4.

Both call the replay-side `replay_render` package (render/, on PYTHONPATH next to
courtcam). Neither is in the default DAG (the default run must not need render/ on the
path, and the render re-encodes the whole game): `--stages director` / `--stages
broadcast` (which runs the director first).

Cache keys: director hashes events, tracks, crops, calibration, game.json (roster names
and team colours reach the graphics) and — once the plays stage registers them —
score.json and plays.json. The render hashes cuts.json (which carries the resolved
score timeline and lower thirds), tracks, crops, calibration and the source video, plus
an optional narration WAV. A director rerun that produces identical cuts leaves the
render a hit.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

from courtcam import pipeline as P

from ..dag import Ctx, Stage
from . import courtcam as cc


def _render_src() -> Path:
    """replay_render's source dir without importing it (the registry must load even
    where render/ is not on the path; the stages then fail with a clear ImportError)."""
    spec = importlib.util.find_spec("replay_render")
    if spec and spec.origin:
        return Path(spec.origin).parent
    return Path(__file__).resolve().parents[4] / "render" / "replay_render"


def _code_hash() -> str:
    h = hashlib.sha256()
    root = _render_src()
    for f in sorted(root.rglob("*.py")):
        h.update(f.relative_to(root).as_posix().encode() + b"\0" + f.read_bytes())
    h.update(Path(__file__).read_bytes())
    return h.hexdigest()[:12]


VERSION = "1+" + _code_hash()
CUTS = "cuts.json"
RENDITION = "renditions/broadcast.mp4"
# score.json / plays.json come from courtcam's plays stage when it is registered; until
# then the director derives a provisional score from events.json (flagged in cuts.json).
_CC_OUTPUTS = {o for s in cc.STAGES for o in s.outputs}
OPTIONAL = tuple(f for f in ("score.json", "plays.json") if f in _CC_OUTPUTS)


def _size(cfg: dict) -> tuple[int, int]:
    w, h = (int(v) for v in str(cfg.get("broadcast_size") or "1920x1080").lower().split("x"))
    return w, h


def run_director(ctx: Ctx, item: str | None) -> None:
    from replay_render.director import direct, validate
    from replay_render.gamedata import load_game

    doc = direct(load_game(ctx.game_dir))
    validate(doc)
    (ctx.game_dir / CUTS).write_text(json.dumps(doc, indent=1), encoding="utf-8")


def run_broadcast(ctx: Ctx, item: str | None) -> None:
    from replay_render.compositor import render

    c = ctx.cfg
    render(
        ctx.game_dir,
        ctx.game_dir / RENDITION,
        size=_size(c),
        t0=float(c.get("broadcast_t0") or 0.0),
        t1=float(c["broadcast_t1"]) if c.get("broadcast_t1") else None,
        crf=int(c.get("broadcast_crf") or 20),
        narration=Path(c["narration"]) if c.get("narration") else None,
        progress=lambda f: ctx.progress("broadcast", f),
    )


STAGES = [
    Stage(
        "director",
        VERSION,
        run_director,
        inputs=("events.json", "tracks", "crops", "calib.json", "game.json", *OPTIONAL),
        outputs=(CUTS,),
        after=("game",),
        default=False,
    ),
    Stage(
        "broadcast",
        VERSION,
        run_broadcast,
        inputs=(CUTS, "tracks", "crops", "calib.json", P.WIDE_REL, "{narration}"),
        outputs=(RENDITION,),
        params=("broadcast_size", "broadcast_t0", "broadcast_t1", "broadcast_crf"),
        after=("director",),
        default=False,
    ),
]
