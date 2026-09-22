"""Stage orchestration (plan §4.4). Every stage is a pure file→file function.

Nothing here knows about a sport: the profile supplies the court, the thresholds and
the event detectors. `run()` reports progress through a `Progress` callback so the
API worker can stream stage status.
"""

from __future__ import annotations

import json
import math
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from . import calibrate as calib_mod
from . import croppath, detect, identity
from . import events as events_mod
from . import ingest as ingest_mod
from .court import on_court, read_court_tracks, resample, write_court_tracks
from .profiles import Profile, load_profile
from .schema import (
    CourtInfo,
    CropPathsRef,
    Event,
    Events,
    Game,
    Renditions,
    TrackFrame,
    TrackPoint,
    TracksChunk,
    TracksRef,
    VideoInfo,
    read_json,
    write_json,
)
from .track import build_tracklets, read_dets, read_tracklets, write_tracklets

Progress = Callable[[str, float], None]
"""`progress(stage_name, fraction)` where fraction is 0.0..1.0 within that stage."""

STAGES: tuple[str, ...] = (
    "ingest",
    "calibrate",
    "detect",
    "track",
    "court",
    "identity",
    "tracks",
    "crops",
    "events",
)
WIDE_REL = "media/wide.mp4"
TRACKS_TEMPLATE = "tracks/{chunk:05d}.json"
CROPS_TEMPLATE = "crops/{player_id}.json"


def _noop(stage: str, fraction: float) -> None:
    return None


def new_game_id() -> str:
    return "g_" + uuid.uuid4().hex[:6]


# --- game.json --------------------------------------------------------------


def _load_game(out_dir: Path) -> Game | None:
    path = out_dir / "game.json"
    return read_json(path, Game) if path.exists() else None


def _save_game(out_dir: Path, game: Game) -> Path:
    return write_json(out_dir / "game.json", game, indent=1)


def _mark(out_dir: Path, game: Game, stage: str, state: str = "done") -> Game:
    game.stages[stage] = state
    _save_game(out_dir, game)
    return game


def record_rendition(out_dir: Path, player_id: str, url: str) -> Path:
    """Point `renditions.players[player_id]` at a lazily rendered MP4 (§4.5)."""
    game = _load_game(out_dir)
    if game is None:
        raise FileNotFoundError(f"{out_dir}/game.json does not exist yet")
    game.renditions.players[player_id] = url
    game.stages["render"] = "partial"
    return _save_game(out_dir, game)


# --- calibration input ------------------------------------------------------


def load_landmarks(
    source: Path | dict[str, Any],
) -> tuple[dict[str, tuple[float, float]], str | None]:
    """Accept a landmarks JSON, a full `calib.json`, or a bare `{name: [x, y]}` dict."""
    raw = (
        json.loads(Path(source).read_text(encoding="utf-8"))
        if isinstance(source, (str, Path))
        else source
    )
    variant = raw.get("variant") if isinstance(raw, dict) else None
    points = raw.get("landmarks_px", raw) if isinstance(raw, dict) else raw
    return {k: (float(v[0]), float(v[1])) for k, v in points.items()}, variant


# --- stages -----------------------------------------------------------------


def stage_ingest(input_path: Path, out_dir: Path, *, force: bool, progress: Progress) -> VideoInfo:
    wide = out_dir / WIDE_REL
    progress("ingest", 0.0)
    if wide.exists() and not force:
        info = ingest_mod.probe(wide)
    else:
        info = ingest_mod.ingest(input_path, wide.parent)
    progress("ingest", 1.0)
    return info


def stage_calibrate(
    out_dir: Path,
    profile: Profile,
    *,
    landmarks_px: dict[str, tuple[float, float]] | None,
    variant: str | None,
    force: bool,
    progress: Progress,
) -> dict[str, Any]:
    path = out_dir / "calib.json"
    progress("calibrate", 0.0)
    if path.exists() and not force:
        calib = calib_mod.read_calib(path)
    else:
        if not landmarks_px:
            raise ValueError("calibration needs --landmarks (or an existing out/calib.json)")
        calib = calib_mod.calibrate(landmarks_px, profile, variant)
        calib_mod.write_calib(path, calib)
    progress("calibrate", 1.0)
    return calib


def stage_detect(
    out_dir: Path,
    profile: Profile,
    info: VideoInfo,
    *,
    detector_kind: str,
    ground_truth: Path | None,
    stride: int,
    max_frames: int | None,
    force: bool,
    show_progress: bool,
    progress: Progress,
) -> Path:
    path = out_dir / "_work" / "dets.json"
    if force and path.exists():
        path.unlink()
    progress("detect", 0.0)
    detector = detect.make_detector(
        detector_kind, profile.detection, fps=info.fps, ground_truth=ground_truth
    )
    detect.run_detect(
        out_dir / WIDE_REL,
        path,
        detector,
        fps=info.fps,
        width=info.width,
        height=info.height,
        stride=stride,
        max_frames=max_frames,
        total_frames=int(info.duration_s * info.fps) or None,
        show_progress=show_progress,
        on_progress=lambda f: progress("detect", f),
    )
    progress("detect", 1.0)
    return path


def stage_track(out_dir: Path, *, force: bool, progress: Progress) -> Path:
    path = out_dir / "_work" / "tracklets.json"
    progress("track", 0.0)
    if force or not path.exists():
        dets = read_dets(out_dir / "_work" / "dets.json")
        write_tracklets(path, build_tracklets(dets), dets)
    progress("track", 1.0)
    return path


def stage_court(
    out_dir: Path, profile: Profile, calib: dict[str, Any], *, force: bool, progress: Progress
) -> Path:
    path = out_dir / "_work" / "court.json"
    progress("court", 0.0)
    if force or not path.exists():
        tracklets, meta = read_tracklets(out_dir / "_work" / "tracklets.json")
        h = np.asarray(calib["H"], dtype=np.float64)
        polygon = np.asarray(calib["court_polygon_m"], dtype=np.float64)
        write_court_tracks(path, on_court(tracklets, h, profile, polygon), meta)
    progress("court", 1.0)
    return path


def stage_identity(out_dir: Path, profile: Profile, *, force: bool, progress: Progress) -> Path:
    path = out_dir / "_work" / "players.json"
    progress("identity", 0.0)
    if force or not path.exists():
        tracks, meta = read_court_tracks(out_dir / "_work" / "court.json")
        players = identity.identify(str(out_dir / WIDE_REL), tracks, profile)
        identity.write_players(path, players, meta)
    progress("identity", 1.0)
    return path


def stage_tracks(
    out_dir: Path, info: VideoInfo, *, rate_hz: int = 10, chunk_s: int = 10, progress: Progress
) -> int:
    """Write `tracks/{chunk:05d}.json` — 10 s chunks at 10 Hz (contract §4.5)."""
    players, _ = identity.read_players(out_dir / "_work" / "players.json")
    n_chunks = max(1, math.ceil(info.duration_s / chunk_s))
    per_chunk = rate_hz * chunk_s
    for c in range(n_chunks):
        t0 = c * chunk_s
        times = t0 + np.arange(per_chunk) / rate_hz
        times = times[times <= info.duration_s + 1e-6]
        rows: list[list[tuple[str, np.ndarray, np.ndarray, float]]] = [[] for _ in times]
        for p in players:
            boxes, court, conf = resample(p.track, times)
            for i in range(len(times)):
                if np.isfinite(boxes[i]).all():
                    rows[i].append((p.player_id, boxes[i], court[i], float(conf[i])))
        chunk = TracksChunk(
            t0=float(t0),
            rate_hz=rate_hz,
            frames=[
                TrackFrame(
                    t=round(float(t), 3),
                    p=[
                        TrackPoint(
                            id=pid,
                            bb=(
                                round(b[0] / info.width, 5),
                                round(b[1] / info.height, 5),
                                round(b[2] / info.width, 5),
                                round(b[3] / info.height, 5),
                            ),
                            ct=(round(float(ct[0]), 3), round(float(ct[1]), 3)),
                            c=round(cf, 3),
                        )
                        for pid, b, ct, cf in rows[i]
                    ],
                )
                for i, t in enumerate(times)
            ],
        )
        write_json(out_dir / TRACKS_TEMPLATE.format(chunk=c), chunk)
        progress("tracks", (c + 1) / n_chunks)
    progress("tracks", 1.0)
    return n_chunks


def stage_crops(
    out_dir: Path, profile: Profile, info: VideoInfo, *, progress: Progress
) -> list[str]:
    players, _ = identity.read_players(out_dir / "_work" / "players.json")
    (out_dir / "crops").mkdir(parents=True, exist_ok=True)
    n = int(round(info.duration_s * 30))
    times = np.arange(n) / 30.0
    written: list[str] = []
    for i, p in enumerate(players):
        boxes, _, _ = resample(p.track, times)
        path = croppath.build_crop_path(
            p.player_id, boxes, info.width, info.height, profile.followcam
        )
        write_json(out_dir / CROPS_TEMPLATE.format(player_id=p.player_id), path)
        written.append(p.player_id)
        progress("crops", (i + 1) / max(1, len(players)))
    progress("crops", 1.0)
    return written


def stage_events(
    out_dir: Path,
    profile: Profile,
    calib: dict[str, Any],
    info: VideoInfo,
    *,
    labeler: events_mod.Labeler | None,
    progress: Progress,
) -> list[Event]:
    progress("events", 0.0)
    players, _ = identity.read_players(out_dir / "_work" / "players.json")
    found = events_mod.detect_events(
        out_dir / WIDE_REL, players, profile, calib, fps=info.fps, labeler=labeler
    )
    write_json(out_dir / "events.json", Events(events=found), indent=1)
    progress("events", 1.0)
    return found


# --- orchestration ----------------------------------------------------------


def run(
    input_path: Path,
    out_dir: Path,
    *,
    sport: str = "basketball",
    variant: str | None = None,
    landmarks_px: dict[str, tuple[float, float]] | None = None,
    calib: Path | None = None,
    detector: str = "yolo",
    ground_truth: Path | None = None,
    stages: Sequence[str] | None = None,
    stride: int | None = None,
    max_frames: int | None = None,
    title: str | None = None,
    game_id: str | None = None,
    recorded_at: str | None = None,
    labeler: events_mod.Labeler | None = None,
    progress: Progress | None = None,
    show_progress: bool = True,
) -> Path:
    """Run the pipeline and return the path to `out_dir/game.json`.

    `stages` runs exactly those stages (and forces them to recompute); omitted, every
    stage runs but skips itself if its output is already on disk. `progress(stage,
    fraction)` is called throughout.
    """
    input_path, out_dir = Path(input_path), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = progress or _noop
    profile = load_profile(sport)
    requested = set(stages) if stages else set(STAGES)
    unknown = requested - set(STAGES)
    if unknown:
        raise ValueError(f"unknown stage(s) {sorted(unknown)}; valid: {list(STAGES)}")
    force = stages is not None
    stride = stride or profile.detection.stride

    if calib is not None and landmarks_px is None:
        landmarks_px, calib_variant = load_landmarks(calib)
        variant = variant or calib_variant
    variant = variant or profile.default_variant()

    info = (
        stage_ingest(input_path, out_dir, force=force, progress=report)
        if "ingest" in requested
        else ingest_mod.probe(out_dir / WIDE_REL)
    )

    game = _load_game(out_dir) or Game(
        id=game_id or new_game_id(),
        title=title or input_path.stem,
        recorded_at=recorded_at,
        status="processing",
        video=info,
        sport=profile.id,
        court=CourtInfo(variant=variant, standard=profile.template(variant).standard),
        renditions=Renditions(wide=WIDE_REL),
        tracks=TracksRef(url_template=TRACKS_TEMPLATE),
        croppaths=CropPathsRef(url_template=CROPS_TEMPLATE),
    )
    game.video = info
    game.status = "processing"
    if "ingest" in requested:
        _mark(out_dir, game, "ingest")

    calib_data = stage_calibrate(
        out_dir,
        profile,
        landmarks_px=landmarks_px,
        variant=variant,
        force=force and "calibrate" in requested,
        progress=report,
    )
    game.court = CourtInfo(
        variant=calib_data.get("variant", variant),
        standard=calib_data.get("standard", "unknown"),
        landmarks_px={k: (v[0], v[1]) for k, v in calib_data.get("landmarks_px", {}).items()},
    )
    if "calibrate" in requested:
        _mark(out_dir, game, "calibrate")

    if "detect" in requested:
        stage_detect(
            out_dir,
            profile,
            info,
            detector_kind=detector,
            ground_truth=ground_truth,
            stride=stride,
            max_frames=max_frames,
            force=force,
            show_progress=show_progress,
            progress=report,
        )
        _mark(out_dir, game, "detect")
    if "track" in requested:
        stage_track(out_dir, force=force, progress=report)
        _mark(out_dir, game, "track")
    if "court" in requested:
        stage_court(out_dir, profile, calib_data, force=force, progress=report)
        _mark(out_dir, game, "court")
    if "identity" in requested:
        stage_identity(out_dir, profile, force=force, progress=report)
        _mark(out_dir, game, "identity")

    if (out_dir / "_work" / "players.json").exists():
        players, _ = identity.read_players(out_dir / "_work" / "players.json")
        game.players, game.teams = identity.to_models(players)

    if "tracks" in requested:
        n_chunks = stage_tracks(out_dir, info, progress=report)
        game.tracks = TracksRef(
            rate_hz=10, chunk_s=10, url_template=TRACKS_TEMPLATE, chunks=n_chunks
        )
        _mark(out_dir, game, "tracks")
    if "crops" in requested:
        stage_crops(out_dir, profile, info, progress=report)
        _mark(out_dir, game, "crops")
    if "events" in requested:
        stage_events(out_dir, profile, calib_data, info, labeler=labeler, progress=report)
        _mark(out_dir, game, "events")

    game.status = "ready" if set(STAGES) <= set(game.stages) else "processing"
    _save_game(out_dir, game)
    return out_dir / "game.json"
