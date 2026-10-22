"""courtcam's pipeline stages (`courtcam.pipeline.STAGES`) as worker stages.

Each stage calls the same `courtcam.pipeline.stage_*` function `pipeline.run` calls, with
the same arguments, so the files it writes are the ones `pipeline.run` writes
(tests/test_courtcam_stages.py diffs the two trees). The last stage, `game`, does the
`game.json` bookkeeping `pipeline.run` interleaves with the stages; it is never cached
because `game.json` also carries the API's identity keys (id, title, recorded_at).

Version = "1+" + a hash of courtcam's source and sport profiles: any change to courtcam
invalidates every courtcam stage. Coarse on purpose — a stale detection is worse than a
recomputed one.
"""

from __future__ import annotations

import functools
import hashlib
from pathlib import Path

from courtcam.profiles import load_profile
from courtcam.schema import CourtInfo, CropPathsRef, Game, Renditions, TracksRef

import courtcam
from courtcam import calibrate as calib_mod
from courtcam import identity, ingest
from courtcam import pipeline as P

from ..dag import Ctx, Stage

SRC = Path(courtcam.__file__).parent


def _code_hash() -> str:
    h = hashlib.sha256()
    for f in sorted(SRC.rglob("*")):
        if f.is_file() and f.suffix in (".py", ".yaml", ".yml", ".json"):
            h.update(f.relative_to(SRC).as_posix().encode() + b"\0" + f.read_bytes())
    return h.hexdigest()[:12]


VERSION = "1+" + _code_hash()
WIDE = P.WIDE_REL
DETS, TRACKLETS, COURT, PLAYERS = (
    "_work/dets.json",
    "_work/tracklets.json",
    "_work/court.json",
    "_work/players.json",
)


@functools.cache
def _device() -> str:
    """Detection swaps in `gpu_model` when torch sees a GPU (D-31), so it is part of the key."""
    import torch

    return "gpu" if torch.cuda.is_available() else "cpu"


def _profile(ctx: Ctx):
    return load_profile(ctx.cfg["sport"])


def _variant(ctx: Ctx) -> str:
    return ctx.cfg.get("variant") or _profile(ctx).default_variant()


def _info(ctx: Ctx):
    return ingest.probe(ctx.game_dir / WIDE)


def _calib(ctx: Ctx) -> dict:
    return calib_mod.read_calib(ctx.game_dir / "calib.json")


def _landmarks(ctx: Ctx) -> dict[str, tuple[float, float]] | None:
    marks = ctx.cfg.get("landmarks_px")
    return {k: (float(v[0]), float(v[1])) for k, v in marks.items()} if marks else None


def run_ingest(ctx: Ctx, item: str | None) -> None:
    P.stage_ingest(Path(ctx.cfg["source"]), ctx.game_dir, force=True, progress=ctx.progress)


def run_calibrate(ctx: Ctx, item: str | None) -> None:
    info = _info(ctx)
    P.stage_calibrate(
        ctx.game_dir,
        _profile(ctx),
        landmarks_px=_landmarks(ctx),
        variant=_variant(ctx),
        image_size=(info.width, info.height),
        force=True,
        progress=ctx.progress,
        low_confidence_override=ctx.cfg.get("low_confidence_override"),
    )


def run_detect(ctx: Ctx, item: str | None) -> None:
    c, profile = ctx.cfg, _profile(ctx)
    P.stage_detect(
        ctx.game_dir,
        profile,
        _info(ctx),
        detector_kind=c.get("detector") or "yolo",
        ground_truth=Path(c["ground_truth"]) if c.get("ground_truth") else None,
        backend=c.get("backend") or "pt",
        model=c.get("model"),
        stride=c.get("stride") or profile.detection.stride,
        max_frames=c.get("max_frames"),
        force=True,
        show_progress=False,
        progress=ctx.progress,
    )


def run_track(ctx: Ctx, item: str | None) -> None:
    P.stage_track(ctx.game_dir, force=True, progress=ctx.progress)


def run_court(ctx: Ctx, item: str | None) -> None:
    P.stage_court(ctx.game_dir, _profile(ctx), _calib(ctx), force=True, progress=ctx.progress)


def run_identity(ctx: Ctx, item: str | None) -> None:
    variant = _calib(ctx).get("variant", _variant(ctx))
    P.stage_identity(ctx.game_dir, _profile(ctx), variant, force=True, progress=ctx.progress)


def run_tracks(ctx: Ctx, item: str | None) -> None:
    P.stage_tracks(ctx.game_dir, _info(ctx), progress=ctx.progress)


def run_crops(ctx: Ctx, item: str | None) -> None:
    P.stage_crops(ctx.game_dir, _profile(ctx), _info(ctx), _calib(ctx), progress=ctx.progress)


def run_audio(ctx: Ctx, item: str | None) -> None:
    P.stage_audio(
        Path(ctx.cfg["source"]), ctx.game_dir, _profile(ctx), _info(ctx), progress=ctx.progress
    )


def _pose_kind(cfg: dict) -> str:
    return P.pose_kind(
        cfg.get("pose"),
        cfg.get("detector") or "yolo",
        Path(cfg["ground_truth"]) if cfg.get("ground_truth") else None,
    )


def _pose_chunks(ctx: Ctx) -> list[str]:
    return sorted(p.stem for p in (ctx.game_dir / "tracks").glob("*.json"))


def run_pose(ctx: Ctx, item: str | None) -> None:
    """One tracks chunk (fan-out item = chunk stem)."""
    c = ctx.cfg
    P.stage_pose(
        ctx.game_dir,
        _profile(ctx),
        _info(ctx),
        kind=_pose_kind(c),
        model=c.get("pose_model"),
        ground_truth=Path(c["ground_truth"]) if c.get("ground_truth") else None,
        chunks=[int(item)] if item is not None else None,
        progress=ctx.progress,
    )


def run_events(ctx: Ctx, item: str | None) -> None:
    P.stage_events(
        ctx.game_dir, _profile(ctx), _calib(ctx), _info(ctx), labeler=None, progress=ctx.progress
    )


def run_triggers(ctx: Ctx, item: str | None) -> None:
    P.stage_triggers(
        ctx.game_dir,
        _profile(ctx),
        _info(ctx),
        asr_model=ctx.cfg.get("asr_model"),
        roster=ctx.cfg.get("roster"),
        progress=ctx.progress,
    )


def run_plays(ctx: Ctx, item: str | None) -> None:
    P.stage_plays(ctx.game_dir, _profile(ctx), _info(ctx), progress=ctx.progress)


def run_game(ctx: Ctx, item: str | None) -> None:
    """`game.json` exactly as `pipeline.run` leaves it after a full run."""
    gd, c, profile = ctx.game_dir, ctx.cfg, _profile(ctx)
    info, calib, variant = _info(ctx), _calib(ctx), _variant(ctx)
    game = P._load_game(gd) or Game(
        id=c.get("game_id") or P.new_game_id(),
        title=c.get("title") or Path(c["source"]).stem,
        recorded_at=c.get("recorded_at"),
        status="processing",
        video=info,
        sport=profile.id,
        court=CourtInfo(variant=variant, standard=profile.template(variant).standard),
        renditions=Renditions(wide=WIDE),
        tracks=TracksRef(url_template=P.TRACKS_TEMPLATE),
        croppaths=CropPathsRef(url_template=P.CROPS_TEMPLATE),
    )
    game.video = info
    game.court = CourtInfo(
        variant=calib.get("variant", variant),
        standard=calib.get("standard", "unknown"),
        landmarks_px={k: (v[0], v[1]) for k, v in calib.get("landmarks_px", {}).items()},
    )
    players, _ = identity.read_players(gd / PLAYERS)
    game.players, game.teams = identity.to_models(players)
    game.tracks = TracksRef(
        rate_hz=10,
        chunk_s=10,
        url_template=P.TRACKS_TEMPLATE,
        chunks=len(list((gd / "tracks").glob("*.json"))),
        people=bool(players) and all(p.solved for p in players),
    )
    for stage in P.STAGES:
        game.stages[stage] = "done"
    game.status = "ready"
    P._save_game(gd, game)


def _detect_resource(cfg: dict) -> str:
    return "gpu" if cfg.get("detector", "yolo") == "yolo" else "cpu"


STAGES = [
    Stage(
        "ingest",
        VERSION,
        run_ingest,
        inputs=("{source}",),
        outputs=(WIDE, "media/thumb.jpg", "media/calib.jpg"),
        resource="cpu",
    ),
    Stage(
        "calibrate",
        VERSION,
        run_calibrate,
        inputs=(WIDE,),
        outputs=("calib.json",),
        params=("sport", "variant", "landmarks_px", "low_confidence_override"),
        after=("ingest",),
    ),
    Stage(
        "detect",
        VERSION,
        run_detect,
        inputs=(WIDE, "{ground_truth}"),
        outputs=(DETS,),
        params=("sport", "detector", "backend", "model", "stride", "max_frames"),
        after=("ingest",),
        resource=_detect_resource,
        key_extra=lambda cfg: _device() if _detect_resource(cfg) == "gpu" else None,
    ),
    Stage("track", VERSION, run_track, inputs=(DETS,), outputs=(TRACKLETS,), after=("detect",)),
    Stage(
        "court",
        VERSION,
        run_court,
        inputs=(TRACKLETS, "calib.json"),
        outputs=(COURT,),
        params=("sport",),
        after=("track", "calibrate"),
    ),
    Stage(
        "identity",
        VERSION,
        run_identity,
        inputs=(COURT, WIDE, "calib.json"),
        outputs=(PLAYERS,),
        params=("sport", "variant"),
        after=("court",),
    ),
    Stage(
        "tracks",
        VERSION,
        run_tracks,
        inputs=(PLAYERS, WIDE),
        outputs=("tracks",),
        after=("identity",),
    ),
    Stage(
        "crops",
        VERSION,
        run_crops,
        inputs=(PLAYERS, "calib.json", WIDE),
        outputs=("crops",),
        params=("sport",),
        after=("identity",),
    ),
    Stage(
        "audio",
        VERSION,
        run_audio,
        inputs=("{source}", WIDE),
        outputs=(P.AUDIO_DIR, "audio.json"),
        params=("sport",),
        after=("ingest",),
    ),
    Stage(
        "pose",
        VERSION,
        run_pose,
        inputs=("tracks/{item}.json", WIDE, "{ground_truth}"),
        outputs=("poses/{item}.json",),
        params=("sport", "pose", "pose_model", "detector"),
        after=("tracks",),
        resource=lambda cfg: "gpu" if _pose_kind(cfg) in ("yolo", "vit") else "cpu",
        fanout=_pose_chunks,
        key_extra=lambda cfg: _device() if _pose_kind(cfg) in ("yolo", "vit") else None,
    ),
    Stage(
        "events",
        VERSION,
        run_events,
        inputs=(PLAYERS, "calib.json", WIDE, "audio.json", "poses"),
        outputs=("events.json", "ball.json"),  # ball.json: courtcam.ball (D-90)
        params=("sport",),
        after=("identity", "audio", "pose"),
    ),
    Stage(
        "triggers",
        VERSION,
        run_triggers,
        inputs=("audio.json", "poses"),
        outputs=("triggers.json",),
        params=("sport", "asr_model", "roster"),
        after=("audio", "pose"),
        resource=lambda cfg: "gpu" if cfg.get("asr_model") else "cpu",
    ),
    Stage(
        "plays",
        VERSION,
        run_plays,
        inputs=("events.json", "triggers.json", WIDE),
        outputs=("plays.json", "clips.json", "score.json"),
        params=("sport",),
        after=("events", "triggers"),
    ),
    Stage(
        "game",
        VERSION,
        run_game,
        inputs=(WIDE, "calib.json", PLAYERS),
        outputs=("game.json",),
        params=("sport", "variant"),
        after=tuple(P.STAGES),
        resource="io",
        cache=False,
    ),
]

assert [s.name for s in STAGES[:-1]] == list(P.STAGES), "courtcam's stage list changed"
