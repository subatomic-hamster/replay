"""Tier C virtual views (M9, image-based since D-86): tierc_scene -> tierc -> tierc_manifest.

* `tierc_scene`    one task per highlight: scene/<play>.json (`replay.scene.v1`): 2D
  keypoints per player at every frame -> 3D joints in court metres (MotionBERT when the
  `lift` extra is installed, else analytic rays + bone lengths) -> clean-up (smoothing,
  bone lengths, foot contacts, collision avoidance) + the modelled ball arc.
  GPU (YOLO pose, MotionBERT) unless the keypoints are a synthetic clip's ground truth
  and the method is analytic.
* `tierc`          one task per play x angle: replays/<play>/tierc_<angle>.mp4
  (wing, courtside, baseline where a cutout can carry it, then pov_<pid> for the key
  player and those nearest them: a virtual POV, manifest id `pov:<pid>`). The 3D scene
  steers the cameras; the people are their real SAM cutouts on billboards over the
  court plate, fading to kit-coloured silhouettes far from the real camera
  (`avatars.imageview`; the stylized avatars of `avatars.render` are no longer shipped).
* `tierc_manifest` one uncached task per play: adds the Tier C angles to
  replays/<play>/manifest.json. The `replays` stage (Tier A/B, virtual.py) writes that
  file from the angle videos it knows; this step merges ours in after it (it replaces
  only `tier == "C"` entries, so re-running either side is safe in this order).

Opt-in (default False): `--stages tierc_manifest` runs the lot, including the Tier A/B
chain it sits on; the API runs it on every upload (replay_api.config
DEFAULT_WORKER_STAGES). Knobs: `tierc_method` (auto | motionbert | analytic), `tierc_kp`
(auto | gt | yolo | poses; auto = the synthetic ground truth when there is one, else
YOLO-pose on the track crops), `pose_model`, `replay_width`.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ..dag import Ctx, Stage
from . import broadcast as bc
from . import courtcam as cc
from .virtual import HIGHLIGHTS, _full, _plays, _width

LABELS = {"wing": "Virtual wing", "courtside": "Virtual courtside",
          "baseline": "Virtual baseline", "pov": "Virtual POV"}  # fmt: skip


def _code_hash() -> str:
    h = hashlib.sha256()
    src = bc._render_src()
    for f in sorted((src / "avatars").glob("*.py")) + [
        src / "virtual" / "tierb.py",
        Path(__file__),
    ]:
        h.update(f.name.encode() + b"\0" + f.read_bytes())
    return h.hexdigest()[:12]


VERSION = "1+" + _code_hash()


def _kp(cfg: dict) -> str:
    kp = cfg.get("tierc_kp") or "auto"
    return ("gt" if cfg.get("ground_truth") else "yolo") if kp == "auto" else kp


def _resource(cfg: dict) -> str:
    return "cpu" if cfg.get("tierc_method") == "analytic" and _kp(cfg) == "gt" else "gpu"


def _lift_available(cfg: dict) -> bool:
    from replay_render.avatars import lift

    return lift.available()


def _angles_of(gd: Path, play_id: str) -> list[str]:
    """A play's Tier C angles from its 3D scene (a virtual POV per reconstructed player),
    else from the highlight (the key player's POV); none for a `lite` fill play. At most
    the highlight's `max_pov` POVs: the key player's first, then the play's other
    participants (a lost man's attacker), then the best-looking."""
    from replay_render.avatars import scene
    from replay_render.avatars.imageview import angles_for
    from replay_render.virtual.replays import play

    h = play(gd, play_id)
    if h.get("lite"):
        return []
    has_scene = (gd / scene.SCENE_REL.format(play_id=play_id)).is_file()
    angles = angles_for(scene.read(gd, play_id) if has_scene else h)
    povs = [a for a in angles if a.startswith("pov_")]
    parts = h.get("participants") or []
    povs = povs[:1] + sorted(povs[1:], key=lambda a: a.removeprefix("pov_") not in parts)
    fixed = [a for a in angles if not a.startswith("pov_")]
    return fixed + povs[: h.get("max_pov", len(povs))]


def _angles(ctx: Ctx) -> list[str]:
    return [f"{p}/tierc_{a}" for p in _full(ctx) for a in _angles_of(ctx.game_dir, p)]


def run_scene(ctx: Ctx, item: str | None) -> None:
    from replay_render.avatars import scene

    kp = _kp(ctx.cfg)
    doc = scene.build(
        ctx.game_dir,
        item,
        ctx.game_dir / cc.WIDE,
        method=ctx.cfg.get("tierc_method") or "auto",
        kp_source=kp,
        ground_truth=Path(ctx.cfg["ground_truth"]) if kp == "gt" else None,
        pose_model=ctx.cfg.get("pose_model"),
    )
    scene.write(ctx.game_dir, item, doc)


def run_render(ctx: Ctx, item: str | None) -> None:
    from replay_render.avatars import imageview, scene

    play_id, stem = item.split("/", 1)
    w = _width(ctx.cfg)
    imageview.render_angle(
        ctx.game_dir,
        ctx.game_dir / cc.WIDE,
        scene.read(ctx.game_dir, play_id),
        stem.removeprefix("tierc_"),
        ctx.game_dir / f"replays/{item}.mp4",
        size=(w, w * 9 // 16 // 2 * 2),
        progress=lambda f: ctx.progress("tierc", f),
    )


def merge_manifest(game_dir: Path, play_id: str, sport: str | None = None) -> dict:
    """Add the rendered Tier C angles of one play to its manifest (created from the
    Tier A/B videos if the `replays` stage has not written it)."""
    from replay_render.virtual.replays import player_name, poster, probe_video, write_manifest

    gd = Path(game_dir)
    path = gd / "replays" / play_id / "manifest.json"
    m = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    if m is None:
        m = write_manifest(gd, play_id, sport)
    angles = [a for a in m.get("angles") or [] if a.get("tier") != "C"]
    names = {p["id"]: p.get("name") for p in _players(gd)}
    for a in _angles_of(gd, play_id):
        rel = f"replays/{play_id}/tierc_{a}.mp4"
        if not (gd / rel).is_file():
            continue
        info = probe_video(gd / rel)
        kind, _, pid = a.partition("_") if a.startswith("pov_") else (a, "", "")
        # `3d:` keeps ids unique: Tier B has a `broadcast_high` too
        aid = f"pov:{pid}" if pid else f"3d:{kind}"
        label = f"{LABELS[kind]} · {player_name(names, pid)}" if pid else LABELS[kind]
        angles.append({"id": aid, "tier": "C", "label": label,
                       **({"player_id": pid} if pid else {}), "url": rel,
                       "poster": poster(gd, rel), "duration_s": info["duration_s"],
                       "width": info["width"], "height": info["height"]})  # fmt: skip
    m["angles"] = angles
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(m, indent=1), encoding="utf-8")
    return m


def _players(gd: Path) -> list[dict]:
    p = gd / "game.json"
    return json.loads(p.read_text(encoding="utf-8")).get("players") or [] if p.exists() else []


def run_manifest(ctx: Ctx, item: str | None) -> None:
    merge_manifest(ctx.game_dir, item, ctx.cfg.get("sport"))


STAGES = [
    Stage(
        "tierc_scene",
        VERSION,
        run_scene,
        inputs=(cc.WIDE, HIGHLIGHTS, "calibration.json", "tracks", "game.json", "{ground_truth}"),
        outputs=("scene/{item}.json",),
        params=("tierc_method", "tierc_kp", "pose_model"),
        after=("highlights", "camera"),
        resource=_resource,
        fanout=_full,
        key_extra=_lift_available,
        default=False,
    ),
    Stage(
        "tierc",
        VERSION,
        run_render,
        inputs=(cc.WIDE, HIGHLIGHTS, "scene", "calibration.json", "plate", "segments", "tracks"),
        outputs=("replays/{item}.mp4",),
        params=("replay_width",),
        after=("tierc_scene", "segment", "plate"),
        fanout=_angles,
        default=False,
    ),
    Stage(
        "tierc_manifest",
        VERSION,
        run_manifest,
        inputs=(HIGHLIGHTS,),
        outputs=("replays/{item}/manifest.json",),
        params=("sport",),
        after=("replays", "tierc"),
        resource="io",
        fanout=_plays,
        cache=False,
        default=False,
    ),
]
