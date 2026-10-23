"""Stage orchestration (plan §4.4). Every stage is a pure file→file function.

Nothing here knows about a sport: the profile supplies the court, the thresholds and
the event detectors. `run()` reports progress through a `Progress` callback so the
API worker can stream stage status.
"""

from __future__ import annotations

import json
import math
import os
import re
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from . import audio as audio_mod
from . import ball as ball_mod
from . import calibrate as calib_mod
from . import croppath, detect, distortion, identity
from . import events as events_mod
from . import ingest as ingest_mod
from . import plays as plays_mod
from . import pose as pose_mod
from . import triggers as triggers_mod
from .court import (
    fit_check,
    on_court,
    polygon_px,
    read_court_tracks,
    resample,
    write_court_tracks,
)
from .profiles import Profile, load_profile
from .schema import (
    AudioDoc,
    Clips,
    CourtInfo,
    CropPathsRef,
    Event,
    Events,
    Game,
    Plays,
    PosesChunk,
    Renditions,
    Score,
    TrackFrame,
    TrackPoint,
    TracksChunk,
    TracksRef,
    Triggers,
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
    "audio",
    "pose",
    "events",
    "triggers",
    "plays",
)
WIDE_REL = "media/wide.mp4"
AUDIO_DIR = "audio"  # always created (empty for a silent source), so it can be cached
AUDIO_WAV_REL = "audio/16k.wav"
AUDIO_FULL_REL = "audio/full.mka"
POSES_TEMPLATE = "poses/{chunk:05d}.json"
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


class LowConfidenceLandmarks(ValueError):
    """Landmarks from an auto-calibration proposal that was not `ok` (D-23, D-24)."""


def low_confidence(raw: Any) -> dict[str, Any] | None:
    """The `autocalib` block of a `courtcam autocalib --out` file whose fit was not ok."""
    block = raw.get("autocalib") if isinstance(raw, dict) else None
    return block if isinstance(block, dict) and block.get("ok") is not True else None


def load_landmarks(
    source: Path | dict[str, Any],
    *,
    accept_low_confidence: bool = False,
) -> tuple[dict[str, tuple[float, float]], str | None]:
    """Accept a landmarks JSON, a full `calib.json`, or a bare `{name: [x, y]}` dict.

    An auto-calibration proposal with `ok: false` is dots to drag, not dots to accept
    (D-23): it is refused unless the caller explicitly accepts it. A 0.74 pickleball fit
    used silently put the court 100-400 px too high and the run found 0 events.
    """
    raw = (
        json.loads(Path(source).read_text(encoding="utf-8"))
        if isinstance(source, (str, Path))
        else source
    )
    block = low_confidence(raw)
    if block is not None and not accept_low_confidence:
        from .autocalib import MIN_TEMPLATE_SCORE

        threshold = block.get("min_score") or MIN_TEMPLATE_SCORE
        score = block.get("score")
        if score is None:  # files written before `score` was in the block
            found = re.search(r"score ([\d.]+) <", block.get("notes") or "")
            score = float(found.group(1)) if found else None
        where = f"{source}: " if isinstance(source, (str, Path)) else ""
        raise LowConfidenceLandmarks(
            f"{where}these landmarks are an auto-calibration proposal with ok=false "
            f"(score {'?' if score is None else f'{score:.2f}'}, threshold "
            f"{threshold:.2f}): dots to drag, not dots to accept. Correct them by "
            "hand and delete the `autocalib` block, or pass --accept-low-confidence."
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


def calibrate_lens(
    landmarks_px: dict[str, tuple[float, float]],
    profile: Profile,
    variant: str | None,
    image_size: tuple[int, int],
) -> dict[str, Any]:
    """`calibrate.calibrate()` on lens-corrected clicks, plus the `k1` that corrected them.

    `calibrate` itself stays lens-free: its gate, its residuals and its payload are the
    contract the API and the uploader are written against. The distortion estimate lives
    here, where the frame size is known — it straightens the clicks, hands them over, and
    then puts the frame back the way the lens sees it:

    * `H` / `H_inv` map **undistorted** pixels ↔ metres, so anything projecting a pixel
      through them undistorts first (`court.to_court`);
    * `landmarks_px` stays as the user clicked it, because the uploader draws dots on it;
    * `court_polygon_px` and `rim_px` are bent back onto the frame, so the overlay, and
      the D-20 court pixel width that sizes the follow-cam, are in frame coordinates.

    `k1 = 0` on an undistorted lens reproduces the old payload exactly (D-24 gate).
    """
    template = profile.template(variant or profile.default_variant())
    names = [n for n in landmarks_px if n in template.landmarks]
    pts = np.asarray([landmarks_px[n] for n in names], dtype=np.float64)
    k1, rms_before, rms_after = distortion.estimate_k1(
        pts, template.landmark_array(names), image_size
    )
    straight = {
        n: (float(p[0]), float(p[1]))
        for n, p in zip(names, distortion.undistort_points(pts, k1, image_size), strict=True)
    }
    calib = calib_mod.calibrate({**landmarks_px, **straight}, profile, variant)
    h_inv = np.asarray(calib["H_inv"], dtype=np.float64)
    calib["k1"] = k1
    calib["image_size"] = [int(image_size[0]), int(image_size[1])]
    calib["lens_rms_px"] = [round(rms_before, 3), round(rms_after, 3)]
    calib["landmarks_px"] = {k: [float(v[0]), float(v[1])] for k, v in landmarks_px.items()}
    calib["court_polygon_px"] = polygon_px(
        template.polygon, h_inv, k1=k1, image_size=image_size
    ).tolist()
    if template.rim:
        calib["rim_px"] = distortion.distort_points([calib["rim_px"]], k1, image_size)[0].tolist()
    return calib


def stage_calibrate(
    out_dir: Path,
    profile: Profile,
    *,
    landmarks_px: dict[str, tuple[float, float]] | None,
    variant: str | None,
    image_size: tuple[int, int],
    force: bool,
    progress: Progress,
    low_confidence_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """`low_confidence_override`: the `autocalib` block of an ok=false proposal the user
    explicitly accepted; it is kept in calib.json so the choice stays visible."""
    path = out_dir / "calib.json"
    progress("calibrate", 0.0)
    if path.exists() and not force:
        calib = calib_mod.read_calib(path)
    else:
        if not landmarks_px:
            raise ValueError("calibration needs --landmarks (or an existing out/calib.json)")
        calib = calibrate_lens(landmarks_px, profile, variant, image_size)
        if low_confidence_override is not None:
            calib["low_confidence_override"] = low_confidence_override
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
    backend: str,
    model: str | None = None,
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
    cfg = profile.detection
    if model:
        cfg = cfg.model_copy(update={"model": model, "gpu_model": None})
    detector = detect.make_detector(
        detector_kind, cfg, fps=info.fps, ground_truth=ground_truth, backend=backend
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
        size = calib.get("image_size")
        lens = {"k1": float(calib.get("k1") or 0.0), "image_size": tuple(size) if size else None}
        fit = fit_check(tracklets, h, profile, polygon, **lens)  # D-94
        tracks = on_court(tracklets, h, profile, polygon, trusted=fit["trusted"], **lens)
        write_court_tracks(path, tracks, {**meta, "fit": fit})
    progress("court", 1.0)
    return path


def stage_identity(
    out_dir: Path, profile: Profile, variant: str, *, force: bool, progress: Progress
) -> Path:
    path = out_dir / "_work" / "players.json"
    progress("identity", 0.0)
    if force or not path.exists():
        tracks, meta = read_court_tracks(out_dir / "_work" / "court.json")
        # `team_rule: net_side` reads the net line off *this variant's* template, so the
        # variant has to come along — badminton singles and doubles are different courts.
        court_ok = (meta.get("fit") or {}).get("trusted", True)
        players = identity.identify(
            str(out_dir / WIDE_REL), tracks, profile, variant, court_ok=court_ok
        )
        # D-97: the detections a player's gaps leave free are theirs
        calib = calib_mod.read_calib(out_dir / "calib.json")
        size = calib.get("image_size")
        players = identity.fill_gaps(
            players,
            read_dets(out_dir / "_work" / "dets.json"),
            np.asarray(calib["H"], dtype=np.float64),
            k1=float(calib.get("k1") or 0.0),
            image_size=tuple(size) if size else None,
            smooth_window=profile.tracking.smooth_window,
        )
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
            boxes, court, conf = resample(p.track, times, identity.max_gap_s(p))
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
    out_dir: Path,
    profile: Profile,
    info: VideoInfo,
    calib: dict[str, Any] | None = None,
    *,
    progress: Progress,
) -> list[str]:
    players, _ = identity.read_players(out_dir / "_work" / "players.json")
    # The follow-cam window scales with how many pixels the court actually spans, so a
    # whole-court panoramic source zooms in far harder than a tight one (croppath).
    court_px_w = croppath.court_px_width(calib, info.width)
    (out_dir / "crops").mkdir(parents=True, exist_ok=True)
    n = int(round(info.duration_s * 30))
    times = np.arange(n) / 30.0
    written: list[str] = []
    for i, p in enumerate(players):
        boxes, _, _ = resample(p.track, times)
        path = croppath.build_crop_path(
            p.player_id, boxes, info.width, info.height, profile.followcam, court_px_w=court_px_w
        )
        write_json(out_dir / CROPS_TEMPLATE.format(player_id=p.player_id), path)
        written.append(p.player_id)
        progress("crops", (i + 1) / max(1, len(players)))
    progress("crops", 1.0)
    return written


def stage_audio(
    input_path: Path, out_dir: Path, profile: Profile, info: VideoInfo, *, progress: Progress
) -> AudioDoc:
    """16 kHz mono WAV + the source's audio stream copied, and `audio.json` (onsets,
    loudness, hype spikes). A silent source gives `has_audio: false` and no media."""
    progress("audio", 0.0)
    wav, full = out_dir / AUDIO_WAV_REL, out_dir / AUDIO_FULL_REL
    (out_dir / AUDIO_DIR).mkdir(parents=True, exist_ok=True)
    for p in (wav, full):
        p.unlink(missing_ok=True)
    ok = audio_mod.extract(Path(input_path), wav, full)
    doc = audio_mod.analyse(wav if ok else None, profile.audio, info.duration_s)
    if ok:
        doc.wav, doc.full = AUDIO_WAV_REL, AUDIO_FULL_REL
    write_json(out_dir / "audio.json", doc)
    progress("audio", 1.0)
    return doc


def pose_kind(kind: str | None, detector_kind: str, ground_truth: Path | None) -> str:
    """`auto`: ground-truth keypoints when detection replays ground truth, else YOLO."""
    if kind and kind != "auto":
        return kind
    return "synthetic" if detector_kind == "synthetic" and ground_truth else "yolo"


def make_poser(kind: str, profile: Profile, model: str | None, ground_truth: Path | None):
    if kind == "yolo":
        return pose_mod.yolo_poser(profile.pose, model or os.environ.get("COURTCAM_POSE_MODEL"))
    if kind == "vit":
        return pose_mod.vitpose_poser(profile.pose, model or os.environ.get("COURTCAM_VIT_MODEL"))
    if kind == "synthetic":
        if ground_truth is None:
            raise ValueError("pose 'synthetic' needs the clip's ground_truth.json")
        return pose_mod.synthetic_poser(ground_truth, profile.pose)
    return None


def stage_pose(
    out_dir: Path,
    profile: Profile,
    info: VideoInfo,
    *,
    kind: str,
    model: str | None = None,
    ground_truth: Path | None = None,
    chunks: Sequence[int] | None = None,
    poser=None,
    progress: Progress,
) -> list[Path]:
    """`poses/{chunk}.json` for every tracks chunk (or just `chunks`). `kind` is
    yolo | synthetic | none."""
    progress("pose", 0.0)
    todo = (
        list(chunks)
        if chunks is not None
        else sorted(int(p.stem) for p in (out_dir / "tracks").glob("*.json"))
    )
    poser = poser or make_poser(kind, profile, model, ground_truth)
    source = {
        "yolo": Path(model or profile.pose.model).name,
        "vit": Path(model or profile.pose.vit_model).name,
        "synthetic": "synthetic",
    }.get(kind, "none")
    written = []
    for n, c in enumerate(todo):
        chunk = read_json(out_dir / TRACKS_TEMPLATE.format(chunk=c), TracksChunk)
        if poser is None:
            doc = PosesChunk(t0=chunk.t0, rate_hz=chunk.rate_hz, frames=[])
        else:
            doc = pose_mod.estimate_chunk(
                chunk,
                (info.width, info.height),
                info.fps,
                poser,
                video=out_dir / WIDE_REL if kind in ("yolo", "vit") else None,
                source=source,
            )
        written.append(write_json(out_dir / POSES_TEMPLATE.format(chunk=c), doc))
        progress("pose", (n + 1) / max(1, len(todo)))
    progress("pose", 1.0)
    return written


def signals(out_dir: Path, info: VideoInfo) -> events_mod.Signals:
    """Audio + pose results for the event and trigger detectors (empty when absent)."""
    sig = events_mod.Signals(size=(info.width, info.height))
    if (out_dir / "audio.json").exists():
        doc = read_json(out_dir / "audio.json", AudioDoc)
        sig.onsets, sig.hype, sig.has_audio = doc.onsets, list(doc.hype), doc.has_audio
    if (out_dir / "poses").is_dir():
        sig.poses = pose_mod.read_poses(out_dir / "poses")
    return sig


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
    sig = signals(out_dir, info)
    # D-90: the ball at the hoop (ball.json), for make/miss from the ball's own path
    sig.ball = ball_mod.run(out_dir / WIDE_REL, out_dir, profile, calib,
                            progress=lambda f: progress("events", 0.8 * f))  # fmt: skip
    found = events_mod.detect_events(
        out_dir / WIDE_REL,
        players,
        profile,
        calib,
        fps=info.fps,
        labeler=labeler,
        signals=sig,
    )
    write_json(out_dir / "events.json", Events(events=found), indent=1)
    progress("events", 1.0)
    return found


def stage_triggers(
    out_dir: Path,
    profile: Profile,
    info: VideoInfo,
    *,
    asr_model: str | None = None,
    roster: dict[str, str] | None = None,
    asr=None,
    progress: Progress,
) -> list:
    """`triggers.json`: X gestures from the poses, voice commands from ASR over the 16 kHz
    WAV (only when an ASR model is configured: `asr_model` or $COURTCAM_ASR_MODEL).
    Unresolved: the plays stage maps them to plays and clips."""
    progress("triggers", 0.0)
    sig = signals(out_dir, info)
    found = triggers_mod.detect_gestures(sig, profile.triggers)
    asr_model = asr_model or os.environ.get("COURTCAM_ASR_MODEL")
    wav = out_dir / AUDIO_WAV_REL
    if (asr or asr_model) and wav.exists():
        samples, sr = audio_mod.read_wav(wav)
        segments = audio_mod.speech_segments(samples, sr, profile.audio)
        if segments:
            found += triggers_mod.detect_voice(
                samples,
                sr,
                segments,
                asr or triggers_mod.whisper_asr(asr_model),
                roster or {},
                profile.triggers,
            )
    progress("triggers", 0.5)
    write_json(out_dir / "triggers.json", Triggers(triggers=triggers_mod.number(found)), indent=1)
    progress("triggers", 1.0)
    return found


def stage_plays(out_dir: Path, profile: Profile, info: VideoInfo, *, progress: Progress) -> list:
    """`plays.json` (grammars over events), `clips.json` (triggers resolved to plays) and
    `score.json` (running score from the events)."""
    progress("plays", 0.0)
    found = read_json(out_dir / "events.json", Events).events
    plays = plays_mod.build_plays(found, profile.plays, profile.id)
    trig = (
        read_json(out_dir / "triggers.json", Triggers).triggers
        if (out_dir / "triggers.json").exists()
        else []
    )
    clips = triggers_mod.apply(trig, plays, profile.triggers, info.duration_s)
    write_json(out_dir / "plays.json", Plays(plays=plays), indent=1)
    write_json(out_dir / "clips.json", Clips(clips=clips), indent=1)
    sc = profile.scoring
    score = plays_mod.score_timeline(found, to=sc.to, win_by=sc.win_by)
    write_json(out_dir / "score.json", Score(score=score), indent=1)
    progress("plays", 1.0)
    return plays


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
    backend: str = "pt",
    model: str | None = None,
    stages: Sequence[str] | None = None,
    stride: int | None = None,
    max_frames: int | None = None,
    title: str | None = None,
    game_id: str | None = None,
    recorded_at: str | None = None,
    labeler: events_mod.Labeler | None = None,
    progress: Progress | None = None,
    show_progress: bool = True,
    pose: str = "auto",
    pose_model: str | None = None,
    asr_model: str | None = None,
    roster: dict[str, str] | None = None,
    accept_low_confidence: bool = False,
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

    override = None
    if calib is not None and landmarks_px is None:
        raw = json.loads(Path(calib).read_text(encoding="utf-8"))
        landmarks_px, calib_variant = load_landmarks(
            raw, accept_low_confidence=accept_low_confidence
        )
        override = low_confidence(raw)
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
        image_size=(info.width, info.height),
        force=force and "calibrate" in requested,
        progress=report,
        low_confidence_override=override,
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
            backend=backend,
            model=model,
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
        stage_identity(out_dir, profile, game.court.variant, force=force, progress=report)
        _mark(out_dir, game, "identity")

    if (out_dir / "_work" / "players.json").exists():
        players, pmeta = identity.read_players(out_dir / "_work" / "players.json")
        game.players, game.teams = identity.to_models(players)
        game.court.trusted = (pmeta.get("fit") or {}).get("trusted")

    if "tracks" in requested:
        n_chunks = stage_tracks(out_dir, info, progress=report)
        ps, _ = identity.read_players(out_dir / "_work" / "players.json")
        game.tracks = TracksRef(
            rate_hz=10,
            chunk_s=10,
            url_template=TRACKS_TEMPLATE,
            chunks=n_chunks,
            people=bool(ps) and all(p.solved for p in ps),
        )
        _mark(out_dir, game, "tracks")
    if "crops" in requested:
        stage_crops(out_dir, profile, info, calib_data, progress=report)
        _mark(out_dir, game, "crops")
    if "audio" in requested:
        stage_audio(input_path, out_dir, profile, info, progress=report)
        _mark(out_dir, game, "audio")
    if "pose" in requested:
        stage_pose(
            out_dir,
            profile,
            info,
            kind=pose_kind(pose, detector, ground_truth),
            model=pose_model,
            ground_truth=ground_truth,
            progress=report,
        )
        _mark(out_dir, game, "pose")
    if "events" in requested:
        stage_events(out_dir, profile, calib_data, info, labeler=labeler, progress=report)
        _mark(out_dir, game, "events")
    if "triggers" in requested:
        names = {p.name: p.id for p in game.players if p.name}
        stage_triggers(
            out_dir, profile, info, asr_model=asr_model, roster=roster or names, progress=report
        )
        _mark(out_dir, game, "triggers")
    if "plays" in requested:
        stage_plays(out_dir, profile, info, progress=report)
        _mark(out_dir, game, "plays")

    game.status = "ready" if set(STAGES) <= set(game.stages) else "processing"
    _save_game(out_dir, game)
    return out_dir / "game.json"
