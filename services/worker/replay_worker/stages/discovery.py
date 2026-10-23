"""M11 discovery stages, all opt-in (`--stages hype|condensed|vertical`), all calling the
replay-side `replay_render` package (render/ on PYTHONPATH, as for the broadcast stages):

* `hype` -> hype.json: the hype meter series + highlight candidates (cheap, CPU);
* `condensed` -> renditions/condensed.mp4 + condensed.json (net sports: rallies only);
* `vertical` -> exports/vertical/<id>.mp4, fanned out over the export specs the API
  writes to exports/vertical/<id>.json (one task per requested clip; the spec id is its
  content hash, so the same request is the same file and a cache hit).
* `reel` -> exports/reel/<id>.mp4 + <id>.plan.json: the highlight reel (top plays and the
  user's clips, replay_render.reel), one task per spec the API wrote to
  exports/reel/<id>.json that has no video yet.

Cache keys hash replay_render's sources (broadcast.VERSION) plus each stage's inputs.
"""

from __future__ import annotations

import dataclasses
import json
import re

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


REEL_DIR = "exports/reel"
REEL_ID = re.compile(r"^r_[0-9a-f]{12}$")


def _reel_ids(ctx: Ctx) -> list[str]:
    """The reel specs the API wrote that have no video yet (one task each)."""
    d = ctx.game_dir / REEL_DIR
    return sorted(p.stem for p in d.glob("r_*.json")
                  if REEL_ID.match(p.stem) and not (d / f"{p.stem}.mp4").exists())  # fmt: skip


def run_reel(ctx: Ctx, item: str | None) -> None:
    from replay_render.reel import render_reel

    d = ctx.game_dir / REEL_DIR
    spec = json.loads((d / f"{item}.json").read_text(encoding="utf-8"))
    render_reel(ctx.game_dir, spec, d / f"{item}.mp4",
                progress=lambda f: ctx.progress("reel", f))  # fmt: skip


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
    Stage(
        "reel",
        VERSION,
        run_reel,
        inputs=(
            f"{REEL_DIR}/{{item}}.json",
            "events.json",
            "game.json",
            "tracks",
            P.WIDE_REL,
            "plays.json?",
            "hype.json?",
            "clips.json?",
            "triggers.json?",
            "edits.json?",  # the user's best-play pick: the reel ends on it
        ),
        outputs=(f"{REEL_DIR}/{{item}}.mp4", f"{REEL_DIR}/{{item}}.plan.json"),
        after=("game",),
        fanout=_reel_ids,
        default=False,
    ),
]


def standalone(name: str) -> dict[str, Stage]:
    """A one-stage registry for a game that is already processed (the API's jobs): the
    stage still caches on its inputs, but does not pull the pipeline in as upstream."""
    stage = next(s for s in STAGES if s.name == name)
    return {name: dataclasses.replace(stage, after=())}
