"""The ONLY module that imports `courtcam`.

courtcam interface used here (verified against courtcam/courtcam/ on 2026-09-22):

    courtcam.pipeline.run(input_path, out_dir, *, sport, variant, landmarks_px, detector,
                          title, game_id, recorded_at, progress, show_progress) -> Path
        # writes out_dir/{game.json, media/wide.mp4, media/thumb.jpg, tracks/, crops/,
        # events.json} and owns game.json while it runs
    courtcam.profiles.available_sports() -> list[str]
    courtcam.profiles.load_profile(sport) -> Profile          # pydantic; .template(variant)
    courtcam.calibrate.calibrate(landmarks_px, profile, variant) -> dict  # reproj_error_px,
        # raises CalibrationError above 5 px
    courtcam.render.render_crop(video, CropPath, out_path, ...) -> Path
    courtcam.schema.CropPath

Every one of these is optional at runtime: if the import fails (courtcam not installed,
no model weights) we log a warning and use fake mode / the static profile.
"""

from __future__ import annotations

import functools
import json
import logging
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from .providers.query import DEFAULT_VOCAB

log = logging.getLogger(__name__)

Progress = Callable[[str, float], None]

# Pipeline-owned keys of game.json (§4.5). Identity keys (id/title/sport/court/...) are
# owned by the API and survive a re-process.
PIPELINE_KEYS = (
    "video",
    "players",
    "teams",
    "tracks",
    "croppaths",
    "renditions",
    "events_url",
)

BASKETBALL_PROFILE: dict = {
    "id": "basketball",
    "display_name": "Basketball",
    "tier": 2,
    "players": {"min": 2, "max": 10},
    "team_rule": "jersey_color",
    "court": {
        "template": "basketball.json",
        "variants": ["half", "full"],
        "landmarks": ["corner_nl", "corner_nr", "corner_fl", "corner_fr", "rim"],
        "margin_m": 1.0,
        "width_m": 15.0,
        "length_m": 14.0,
        "x_range": [-7.5, 7.5],
        "y_range": [0.0, 14.0],
    },
    "events": ["shot", "bookmark"],
    "query_vocab": {k: v for k, v in DEFAULT_VOCAB.items() if v["type"] in ("shot", "bookmark")},
    "sport_ui": {
        "chips": ["All shots", "Makes", "Misses", "Top plays", "Bookmarks"],
        "review": ["shot_chart", "heatmap", "box_score"],
        "event_types": ["shot", "bookmark"],
        "court": {
            "units": "m",
            "outline": [[-7.5, 0.0], [7.5, 0.0], [7.5, 14.0], [-7.5, 14.0]],
            "rim": [0.0, 1.575],
            "three_point_radius_m": 6.75,
            "free_throw_line_y_m": 5.8,
        },
    },
}


# --------------------------------------------------------------------------- profiles


class CalibrationRejected(ValueError):
    """courtcam refused the landmark clicks (reprojection error too high)."""


def _profile_dict(profile) -> dict:
    d = profile.model_dump(mode="json", by_alias=True)
    try:  # court extents in metres, for the shot chart / heatmap bins
        template = profile.template()
        poly = template.polygon
        d["court"]["x_range"] = [float(poly[:, 0].min()), float(poly[:, 0].max())]
        d["court"]["y_range"] = [float(poly[:, 1].min()), float(poly[:, 1].max())]
        d["court"]["size_m"] = [float(v) for v in template.size]
        d["court"]["standard"] = template.standard
    except Exception as exc:  # noqa: BLE001
        log.info("no court template extents for %s (%s)", d.get("id"), exc)
    return d


def list_sports() -> list[dict]:
    try:
        from courtcam.profiles import available_sports, load_profile  # type: ignore

        profiles = [_profile_dict(load_profile(sid)) for sid in available_sports()]
        if profiles:
            return profiles
    except Exception as exc:  # noqa: BLE001 - any failure means "use the fallback"
        log.warning("courtcam sport profiles unavailable (%s); serving static basketball", exc)
    return [BASKETBALL_PROFILE]


def get_profile(sport: str) -> dict | None:
    return next((p for p in list_sports() if p.get("id") == sport), None)


def calibration_error(sport: str, variant: str, landmarks_px: dict) -> float | None:
    """Reprojection error in px; None when courtcam cannot compute it.

    Raises CalibrationRejected when the clicks are too far off to be usable.
    """
    try:
        from courtcam.calibrate import CalibrationError, calibrate  # type: ignore
        from courtcam.profiles import load_profile  # type: ignore
    except Exception as exc:  # noqa: BLE001
        log.info("courtcam calibration unavailable (%s)", exc)
        return None
    try:
        calib = calibrate(dict(landmarks_px), load_profile(sport), variant)
    except CalibrationError as exc:
        raise CalibrationRejected(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - bad template/landmarks: not fatal to the API
        log.info("reprojection error unavailable (%s)", exc)
        return None
    return float(calib["reproj_error_px"])


# --------------------------------------------------------------------------- run


def run(
    input_path: Path,
    out_dir: Path,
    game: dict,
    progress: Progress,
    pipeline: str = "courtcam",
    fake_dir: Path | None = None,
    detector: str = "yolo",
) -> dict:
    """Process `input_path` into `out_dir`; return the game.json keys the pipeline owns."""
    court = game.get("court") or {}
    if pipeline != "fake":
        try:
            from courtcam.pipeline import run as run_pipeline  # type: ignore
        except Exception as exc:  # noqa: BLE001
            log.warning("courtcam import failed (%s); falling back to REPLAY_PIPELINE=fake", exc)
        else:
            _prepare_for_courtcam(Path(out_dir), game)
            run_pipeline(
                Path(input_path),
                Path(out_dir),
                sport=game.get("sport", "basketball"),
                variant=court.get("variant"),
                landmarks_px={k: tuple(v) for k, v in (court.get("landmarks_px") or {}).items()},
                detector=detector,
                title=game.get("title"),
                game_id=game.get("id"),
                recorded_at=game.get("recorded_at"),
                progress=progress,
                show_progress=False,
            )
            return _pipeline_keys(Path(out_dir) / "game.json")
    return _run_fake(input_path, out_dir, fake_dir, progress)


def render_player(game_dir: Path, player_id: str, progress: Progress, pipeline: str) -> str | None:
    """Render one follow-cam rendition (plan §4.4 step 9, lazily, on request).

    Returns its path relative to the game dir, or None in fake mode.
    """
    game_dir = Path(game_dir)
    if pipeline != "fake":
        try:
            from courtcam.render import render_crop  # type: ignore
            from courtcam.schema import CropPath  # type: ignore

            crops = CropPath.model_validate_json((game_dir / f"crops/{player_id}.json").read_text())
            rel = f"media/{player_id}.mp4"
            render_crop(
                game_dir / "media/wide.mp4",
                crops,
                game_dir / rel,
                progress=progress,
                show_progress=False,
            )
            return rel
        except Exception as exc:  # noqa: BLE001
            log.warning("courtcam render unavailable (%s); marking rendition done (fake)", exc)
    progress("render", 1.0)
    return None


def _prepare_for_courtcam(out_dir: Path, game: dict) -> None:
    """courtcam re-validates an existing game.json against `replay.game.v1`; the API's
    stub has nulls where the pipeline has not filled anything in yet. Write a valid one
    so courtcam keeps our id/title/court instead of choking on it."""
    stub = {k: v for k, v in game.items() if v is not None}
    rend = stub.get("renditions") or {}
    stub["renditions"] = {
        "wide": rend.get("wide") or "media/wide.mp4",
        "players": rend.get("players") or {},
    }
    (out_dir / "game.json").write_text(json.dumps(stub, indent=1))


# --------------------------------------------------------------------------- fake mode


def _run_fake(input_path: Path, out_dir: Path, fake_dir: Path | None, progress: Progress) -> dict:
    """Copy a fixture output tree + transcode the upload, so the web app and Playwright
    can run the whole flow with no model."""
    fake_dir = Path(fake_dir) if fake_dir else Path(__file__).parent.parent / "fixtures/fake_game"
    if not fake_dir.is_dir():
        raise FileNotFoundError(f"REPLAY_FAKE_PIPELINE_DIR not found: {fake_dir}")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    progress("ingest", 0.1)
    media = out_dir / "media"
    media.mkdir(exist_ok=True)
    _transcode(Path(input_path), media / "wide.mp4")
    _thumbnail(media / "wide.mp4", media / "thumb.jpg")
    progress("ingest", 1.0)

    for stage in ("detect", "track"):
        progress(stage, 0.5)
    # game.json stays API-owned: the fixture's copy would reset id/title/status mid-run
    shutil.copytree(
        fake_dir, out_dir, dirs_exist_ok=True, ignore=shutil.ignore_patterns("game.json")
    )
    progress("detect", 1.0)
    progress("track", 1.0)
    progress("render", 1.0)
    progress("label", 1.0)

    keys = _pipeline_keys(fake_dir / "game.json")
    probed = _probe(media / "wide.mp4")
    if probed:
        keys["video"] = {**keys.get("video", {}), **probed}
    return keys


@functools.cache
def _h264_encoder() -> str | None:
    """Fedora's ffmpeg ships libopenh264, not libx264 — pick whichever exists."""
    try:
        out = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return next((enc for enc in ("libx264", "libopenh264") if enc in out), None)


def _transcode(src: Path, dst: Path) -> None:
    """D-3: progressive faststart H.264 30 fps mezzanine; the API serves it with ranges."""
    enc = _h264_encoder()
    if enc is None:
        log.warning("no software H.264 encoder; copying source verbatim")
        shutil.copyfile(src, dst)
        return
    quality = ["-preset", "veryfast", "-crf", "26"] if enc == "libx264" else ["-b:v", "2M"]
    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-i",
        str(src),
        "-c:v",
        enc,
        *quality,
        "-r",
        "30",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
        str(dst),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=1800)
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("ffmpeg transcode failed (%s); copying source verbatim", exc)
        shutil.copyfile(src, dst)


def _thumbnail(src: Path, dst: Path) -> None:
    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-ss",
        "1",
        "-i",
        str(src),
        "-frames:v",
        "1",
        "-q:v",
        "4",
        str(dst),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("ffmpeg thumbnail failed (%s)", exc)


def _probe(path: Path) -> dict | None:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,r_frame_rate:format=duration",
        "-of",
        "json",
        str(path),
    ]
    try:
        out = subprocess.run(cmd, check=True, capture_output=True, timeout=60).stdout
        data = json.loads(out)
        st = data["streams"][0]
        num, _, den = st["r_frame_rate"].partition("/")
        return {
            "width": int(st["width"]),
            "height": int(st["height"]),
            "fps": round(int(num) / int(den or 1), 3),
            "duration_s": round(float(data["format"]["duration"]), 3),
        }
    except (OSError, subprocess.SubprocessError, KeyError, ValueError) as exc:
        log.warning("ffprobe failed (%s); keeping fixture video metadata", exc)
        return None


def _pipeline_keys(game_json: Path) -> dict:
    data = json.loads(Path(game_json).read_text())
    return {k: data[k] for k in PIPELINE_KEYS if k in data}
