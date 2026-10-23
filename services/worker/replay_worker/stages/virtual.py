"""Virtual replay angles (M8): camera -> plate -> highlights -> segment -> tiera/tierb
-> replays. The worker's first per-play x per-angle fan-out.

* `camera`  calib.json -> calibration.json (K, R, t; courtcam.calibrate.camera_calibration)
* `plate`   temporal-median court plate + top-down floor + backdrop (courtcam.plate)
* `highlights` replays/highlights.json: the plays to render (replay_render.virtual.replays)
* `segment` one task per play, GPU: SAM 2.1 masks (segments/<play>.npz)
* `tiera`   one task per play x real-video angle (wide, follow_<pid>, tight_<pid>)
* `tierb`   one task per play x 2.5D angle (broadcast_high, orbit, push_in)
* `replays` one task per play: replays/<play>/manifest.json (uncached bookkeeping:
  it lists whichever angle videos exist)
* `scene`   one task per play: replays/<play>/scene/ (`replay.scene_package.v1`: plate
  textures, player atlas video, layout.json with the camera envelope) for clients that
  render the 2.5D scene live (docs/scene-format.md)

None is in the default DAG (the default run must not need render/ or a GPU model):
`--stages replays` runs the lot. Run-config knobs: `highlights_n` (how many plays at
least, with top hype plays as fill; default about 1.5 per minute of game, 3 to 10:
replays.auto_n; the best play, the user's and the story events always count),
`segment_fake=1` (elliptical masks from the boxes, no model: CPU tests), `sam_model`.
Synthetic input (`detector=synthetic`) labels every output SYNTHETIC.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from courtcam.profiles import load_profile

from courtcam import calibrate as calib_mod
from courtcam import plate as plate_mod

from ..dag import Ctx, Stage
from . import broadcast as bc
from . import courtcam as cc

HIGHLIGHTS = "replays/highlights.json"
TIER_B = ("broadcast_high", "orbit", "push_in")


def _version(*virtual: str, courtcam: tuple = ()) -> str:
    """Per stage: only the modules that stage runs, so a renderer edit does not throw
    away the (GPU) masks and a mask change does not re-render Tier A."""
    h = hashlib.sha256()
    root = bc._render_src() / "virtual"
    for f in [root / f"{v}.py" for v in virtual] + [Path(m.__file__) for m in courtcam]:
        h.update(f.name.encode() + b"\0" + f.read_bytes())
    return "1+" + h.hexdigest()[:12]


_CC_OUTPUTS = {o for s in cc.STAGES for o in s.outputs}
OPTIONAL = tuple(f for f in ("plays.json",) if f in _CC_OUTPUTS)


def _video(ctx: Ctx) -> Path:
    return ctx.game_dir / cc.WIDE


def _plays(ctx: Ctx, full: bool = False) -> list[str]:
    """The highlights' play ids; `full`: only those with 3D angles (masks, Tier B, the
    scene, Tier C), not the `lite` fill plays (real-video angles only)."""
    path = ctx.game_dir / HIGHLIGHTS
    if not path.exists():
        return []
    plays = json.loads(path.read_text(encoding="utf-8"))["plays"]
    return [p["play_id"] for p in plays if not (full and p.get("lite"))]


def _full(ctx: Ctx) -> list[str]:
    return _plays(ctx, full=True)


def _angles(ctx: Ctx, tier: str) -> list[str]:
    from replay_render.virtual.replays import angle_files, read_highlights

    return [
        f"{h['play_id']}/{stem}"
        for h in read_highlights(ctx.game_dir)["plays"]
        for stem, _, t in angle_files(h)
        if t == tier
    ]


def run_camera(ctx: Ctx, item: str | None) -> None:
    calib = calib_mod.read_calib(ctx.game_dir / "calib.json")
    cal = calib_mod.camera_calibration(calib, load_profile(ctx.cfg["sport"]))
    (ctx.game_dir / "calibration.json").write_text(json.dumps(cal, indent=1), encoding="utf-8")


def run_plate(ctx: Ctx, item: str | None) -> None:
    gd = ctx.game_dir
    plate_mod.build_plate(
        _video(ctx),
        calib_mod.read_calib(gd / "calib.json"),
        json.loads((gd / "calibration.json").read_text(encoding="utf-8")),
        gd / "plate",
        tracks_dir=gd / "tracks",
        progress=lambda f: ctx.progress("plate", f),
    )


def run_highlights(ctx: Ctx, item: str | None) -> None:
    from replay_render.virtual.replays import write_highlights

    write_highlights(
        ctx.game_dir,
        n=int(ctx.cfg.get("highlights_n") or 0) or None,  # None: ~one a minute of game
        synthetic=ctx.cfg.get("detector") == "synthetic",
    )


def _fake(cfg: dict) -> bool:
    return str(cfg.get("segment_fake") or "").lower() in ("1", "true", "yes")


def run_segment(ctx: Ctx, item: str | None) -> None:
    from replay_render.virtual.segment import MODEL_ID, segment_play

    segment_play(
        ctx.game_dir,
        _video(ctx),
        item,
        fake=_fake(ctx.cfg),
        model_id=ctx.cfg.get("sam_model") or MODEL_ID,
        progress=lambda f: ctx.progress("segment", f),
    )


def run_tiera(ctx: Ctx, item: str | None) -> None:
    from replay_render.virtual import tiera

    play_id, stem = item.split("/", 1)
    out = ctx.game_dir / f"replays/{item}.mp4"
    tiera.render_angle(ctx.game_dir, _video(ctx), play_id, stem, out, out_w=_width(ctx.cfg))


def run_tierb(ctx: Ctx, item: str | None) -> None:
    from replay_render.virtual import tierb

    play_id, angle = item.split("/", 1)
    w = _width(ctx.cfg)
    out = ctx.game_dir / f"replays/{item}.mp4"
    tierb.render_angle(
        ctx.game_dir, _video(ctx), play_id, angle, out, size=(w, w * 9 // 16 // 2 * 2)
    )


def _width(cfg: dict) -> int:
    return int(cfg.get("replay_width") or 1280) // 2 * 2


def run_scene(ctx: Ctx, item: str | None) -> None:
    from replay_render.virtual import scene

    scene.build_package(
        ctx.game_dir, _video(ctx), item, progress=lambda f: ctx.progress("scene", f)
    )


def run_replays(ctx: Ctx, item: str | None) -> None:
    from replay_render.virtual.replays import write_manifest

    write_manifest(ctx.game_dir, item, ctx.cfg.get("sport"))


STAGES = [
    Stage(
        "camera",
        _version(courtcam=(calib_mod,)),
        run_camera,
        inputs=("calib.json",),
        outputs=("calibration.json",),
        params=("sport",),
        after=("calibrate",),
        default=False,
    ),
    Stage(
        "plate",
        _version(courtcam=(calib_mod, plate_mod)),
        run_plate,
        inputs=(cc.WIDE, "calib.json", "calibration.json", "tracks"),
        outputs=("plate",),
        after=("camera", "tracks"),
        default=False,
    ),
    Stage(
        "highlights",
        _version("replays"),
        run_highlights,
        # the best play: the user's pick (edits.json), the game winner, else the top hype
        inputs=(
            "events.json",
            "tracks",
            "game.json",
            *OPTIONAL,
            "hype.json?",
            "clips.json?",
            "edits.json?",
        ),
        outputs=(HIGHLIGHTS,),
        params=("highlights_n", "detector"),
        after=("game", "hype"),
        resource="io",
        default=False,
    ),
    Stage(
        "segment",
        _version("segment", "replays"),
        run_segment,
        inputs=(cc.WIDE, HIGHLIGHTS, "tracks"),
        outputs=("segments/{item}.npz", "segments/{item}.json"),
        params=("segment_fake", "sam_model"),
        after=("highlights",),
        resource=lambda cfg: "cpu" if _fake(cfg) else "gpu",
        fanout=_full,
        default=False,
    ),
    Stage(
        "tiera",
        _version("tiera", "replays"),
        run_tiera,
        inputs=(cc.WIDE, HIGHLIGHTS, "tracks", "crops"),
        outputs=("replays/{item}.mp4",),
        params=("replay_width",),
        after=("highlights",),
        fanout=lambda ctx: _angles(ctx, "A"),
        default=False,
    ),
    Stage(
        "tierb",
        _version("tierb", "segment", "replays", courtcam=(calib_mod,)),
        run_tierb,
        inputs=(cc.WIDE, HIGHLIGHTS, "calibration.json", "plate", "segments", "tracks"),
        outputs=("replays/{item}.mp4",),
        params=("replay_width",),
        after=("segment", "plate"),
        fanout=lambda ctx: _angles(ctx, "B"),
        default=False,
    ),
    Stage(
        "scene",
        _version("scene", "tierb", "segment", "replays", courtcam=(calib_mod, plate_mod)),
        run_scene,
        inputs=(
            cc.WIDE,
            HIGHLIGHTS,
            "calib.json",
            "calibration.json",
            "plate",
            "segments/{item}.npz",
            "segments/{item}.json",
            "tracks",
            "game.json",
        ),
        outputs=("replays/{item}/scene",),
        after=("segment", "plate"),
        fanout=_full,
        default=False,
    ),
    Stage(
        "replays",
        _version("replays"),
        run_replays,
        inputs=(HIGHLIGHTS,),
        outputs=("replays/{item}/manifest.json",),
        params=("sport",),
        after=("tiera", "tierb"),
        resource="io",
        fanout=_plays,
        cache=False,
        default=False,
    ),
]
