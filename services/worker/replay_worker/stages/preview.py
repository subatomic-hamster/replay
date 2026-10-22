"""TV redesign stages, both in the default DAG (cheap, CPU, ffmpeg/OpenCV only):

* `storyboard` -> storyboard/NNNN.jpg + storyboard/manifest.json: seek previews, one
  320x180 frame every 2 s tiled 10x10 per sheet, from the wide mezzanine. Right after
  ingest, so a game being processed can already be scrubbed.
* `moments` -> moments.json, moments/<event id>.jpg and media/hero.jpg: a thumb per
  detected event at `t_key` with its plain label, and the library's hero frame (the top
  hype candidate when the opt-in `hype` stage ran, else the best event, else mid-game).

Both call `replay_api.moments` (services/api on PYTHONPATH, as for the narrate and faces
stages), which the API's routes and its fake pipeline share. Version = hash of that module
and this file. `moments` hashes events, game.json (player names) and, when present,
hype.json; `soft_after=("hype",)` orders it after hype when both run.
"""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

from courtcam import pipeline as P

from ..dag import Ctx, Stage


def _code_hash() -> str:
    spec = importlib.util.find_spec("replay_api")
    root = (
        Path(spec.origin).parent
        if spec and spec.origin
        else Path(__file__).resolve().parents[3] / "api" / "replay_api"
    )
    h = hashlib.sha256(Path(__file__).read_bytes())
    h.update((root / "moments.py").read_bytes())
    return h.hexdigest()[:12]


VERSION = _code_hash()


def run_storyboard(ctx: Ctx, item: str | None) -> None:
    from replay_api import moments as M

    M.write_storyboard(ctx.game_dir / P.WIDE_REL, ctx.game_dir)


def run_moments(ctx: Ctx, item: str | None) -> None:
    from replay_api import moments as M

    M.write_moments(ctx.game_dir)


STAGES = [
    Stage(
        "storyboard",
        VERSION,
        run_storyboard,
        inputs=(P.WIDE_REL,),
        outputs=("storyboard",),
        after=("ingest",),
    ),
    Stage(
        "moments",
        VERSION,
        run_moments,
        inputs=(
            "events.json",
            "game.json",
            P.WIDE_REL,
            "hype.json?",
            "triggers.json?",
            "clips.json?",
        ),
        outputs=("moments.json", "moments", "media/hero.jpg"),
        after=("game",),
        soft_after=("hype",),
    ),
]
