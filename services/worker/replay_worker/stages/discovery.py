"""M11 discovery stages, all opt-in (`--stages hype|condensed|vertical`), all calling the
replay-side `replay_render` package (render/ on PYTHONPATH, as for the broadcast stages):

* `hype` -> hype.json: the hype meter series + highlight candidates (cheap, CPU);
* `condensed` -> renditions/condensed.mp4 + condensed.json (net sports: rallies only);
* `vertical` -> exports/vertical/<id>.mp4, fanned out over the export specs the API
  writes to exports/vertical/<id>.json (one task per requested clip; the spec id is its
  content hash, so the same request is the same file and a cache hit).

Cache keys hash replay_render's sources (broadcast.VERSION) plus each stage's inputs.
"""

from __future__ import annotations

import dataclasses
import json

from courtcam import pipeline as P

from ..dag import Ctx, Stage
from . import broadcast as B

VERSION = B.VERSION
VERTICAL_DIR = "exports/vertical"


def run_hype(ctx: Ctx, item: str | None) -> None:
    from replay_render.gamedata import load_game
    from replay_render.hype import REL, hype_series

    doc = hype_series(load_game(ctx.game_dir))
    (ctx.game_dir / REL).write_text(json.dumps(doc), encoding="utf-8")


def _size(text: str | None, default: str) -> tuple[int, int]:
    w, h = (int(v) for v in str(text or default).lower().split("x"))
    return w, h


def run_condensed(ctx: Ctx, item: str | None) -> None:
    from replay_render.condensed import render_condensed

    render_condensed(
        ctx.game_dir,
        size=_size(ctx.cfg.get("condensed_size"), "1280x720"),
        crf=int(ctx.cfg.get("condensed_crf") or 26),
        progress=lambda f: ctx.progress("condensed", f),
    )


def _export_ids(ctx: Ctx) -> list[str]:
    return sorted(p.stem for p in (ctx.game_dir / VERTICAL_DIR).glob("v_*.json"))


def run_vertical(ctx: Ctx, item: str | None) -> None:
    from replay_render.vertical import export

    spec_path = ctx.game_dir / VERTICAL_DIR / f"{item}.json"
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    export(
        ctx.game_dir,
        spec,
        ctx.game_dir / VERTICAL_DIR / f"{item}.mp4",
        size=tuple(spec.get("size") or (720, 1280)),
        progress=lambda f: ctx.progress("vertical", f),
    )


GAME_FILES = ("events.json", "plays.json", "tracks", "calib.json", "game.json")


STAGES = [
    Stage(
        "hype",
        VERSION,
        run_hype,
        inputs=(*GAME_FILES, "audio.json", "poses"),
        outputs=("hype.json",),
        after=("game",),
        default=False,
    ),
    Stage(
        "condensed",
        VERSION,
        run_condensed,
        inputs=(*GAME_FILES, "score.json", P.WIDE_REL),
        outputs=("renditions/condensed.mp4", "condensed.json"),
        params=("condensed_size", "condensed_crf"),
        after=("game",),
        default=False,
    ),
    Stage(
        "vertical",
        VERSION,
        run_vertical,
        inputs=(f"{VERTICAL_DIR}/{{item}}.json", "tracks", "game.json", P.WIDE_REL),
        outputs=(f"{VERTICAL_DIR}/{{item}}.mp4",),
        after=("game",),
        fanout=_export_ids,
        default=False,
    ),
]


def standalone(name: str) -> dict[str, Stage]:
    """A one-stage registry for a game that is already processed (the API's jobs): the
    stage still caches on its inputs, but does not pull the pipeline in as upstream."""
    stage = next(s for s in STAGES if s.name == name)
    return {name: dataclasses.replace(stage, after=())}
