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
    courtcam.autocalib.autocalibrate(frame_bgr, profile, variant, backend=...) -> Proposal
    courtcam.autocalib.read_frame(path) -> np.ndarray
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
import time
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
    "landmarks": ["corner_nl", "corner_nr", "corner_fl", "corner_fr", "rim"],
    "variants": ["half", "full"],
    "sport_ui": {
        "chips": ["All shots", "Makes", "Misses", "Top plays", "Bookmarks"],
        "review": ["shot_chart", "heatmap", "box_score"],
        "event_types": ["shot", "bookmark"],
        "court": {
            "size_m": [15.0, 14.0],
            "x_range": [-7.5, 7.5],
            "y_range": [0.0, 14.0],
            "polygons": {
                "outline": [[-7.5, 0.0], [7.5, 0.0], [7.5, 14.0], [-7.5, 14.0]],
                "paint": [[-2.45, 0.0], [2.45, 0.0], [2.45, 5.8], [-2.45, 5.8]],
            },
        },
    },
}


# --------------------------------------------------------------------------- profiles


class CalibrationRejected(ValueError):
    """courtcam refused the landmark clicks (reprojection error too high)."""


def _profile_dict(profile, variant: str | None = None) -> dict:
    d = profile.model_dump(mode="json", by_alias=True)
    # D-13: the clients read `landmarks`/`variants` at the top level; the nested
    # `court` block stays for the pipeline.
    court = d.get("court") or {}
    d["landmarks"] = list(court.get("landmarks") or [])
    d["landmarks_optional"] = list(court.get("landmarks_optional") or [])
    d["variants"] = list(court.get("variants") or [])
    try:  # court extents in metres, for the shot chart / heatmap bins
        template = profile.template(variant)
        poly = template.polygon
        court["x_range"] = [float(poly[:, 0].min()), float(poly[:, 0].max())]
        court["y_range"] = [float(poly[:, 1].min()), float(poly[:, 1].max())]
        court["size_m"] = [float(v) for v in template.size]
        court["standard"] = template.standard
        d.setdefault("sport_ui", {})["court"] = _ui_court(template, court)
    except Exception as exc:  # noqa: BLE001
        log.info("no court template extents for %s (%s)", d.get("id"), exc)
    return d


def _ui_court(template, court: dict) -> dict:
    """`sport_ui.court` as the TV draws it: metre polygons plus the axis ranges, so a
    court whose origin is the baseline centre (x < 0 on the left) still fits the SVG."""
    return {
        "size_m": court["size_m"],
        "x_range": court["x_range"],
        "y_range": court["y_range"],
        "polygons": {
            "outline": [[float(x), float(y)] for x, y in template.court],
            **{
                name: [[float(x), float(y)] for x, y in pts]
                for name, pts in (template.features or {}).items()
            },
        },
    }


def list_sports() -> list[dict]:
    """The sport catalog, best-supported first.

    Order is the contract: `/sports` is a bare array (D-13) and the uploader's picker
    defaults to element 0, so the highest tier has to lead. courtcam lists its profiles
    alphabetically, which silently made badminton the default the moment it shipped.
    """
    try:
        from courtcam.profiles import available_sports, load_profile  # type: ignore

        profiles = [_profile_dict(load_profile(sid)) for sid in available_sports()]
        if profiles:
            return sorted(profiles, key=lambda p: (-int(p.get("tier") or 1), p["id"]))
    except Exception as exc:  # noqa: BLE001 - any failure means "use the fallback"
        log.warning("courtcam sport profiles unavailable (%s); serving static basketball", exc)
    return [BASKETBALL_PROFILE]


def get_profile(sport: str, variant: str | None = None) -> dict | None:
    """The catalog entry, or — with `variant` — one whose court extents and `sport_ui`
    come from *that* variant's template. Without it a full-court game was served the
    half-court polygon, so the court inset, the shot chart and the heatmap all drew the
    wrong court and binned positions outside their own range."""
    if variant:
        try:
            from courtcam.profiles import load_profile  # type: ignore

            return _profile_dict(load_profile(sport), variant)
        except Exception as exc:  # noqa: BLE001 - fall back to the variant-less catalog
            log.info("no %s profile for variant %r (%s)", sport, variant, exc)
    return next((p for p in list_sports() if p.get("id") == sport), None)


def calibration_error(
    sport: str, variant: str, landmarks_px: dict
) -> tuple[float | None, dict[str, float]]:
    """`(reprojection error in px, per-landmark residuals)`.

    The error is None when courtcam cannot compute it, and the residuals are then empty.
    They are what lets the uploader point at the one click that is off instead of just
    printing a number (bug 3). Raises CalibrationRejected when the clicks are unusable.
    """
    try:
        from courtcam.calibrate import CalibrationError, calibrate  # type: ignore
        from courtcam.profiles import load_profile  # type: ignore
    except Exception as exc:  # noqa: BLE001
        log.info("courtcam calibration unavailable (%s)", exc)
        return None, {}
    try:
        calib = calibrate(dict(landmarks_px), load_profile(sport), variant)
    except CalibrationError as exc:
        raise CalibrationRejected(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - bad template/landmarks: not fatal to the API
        log.info("reprojection error unavailable (%s)", exc)
        return None, {}
    return float(calib["reproj_error_px"]), {
        k: float(v) for k, v in (calib.get("residuals_px") or {}).items()
    }


EMPTY_PROPOSAL: dict = {
    "landmarks_px": {},
    "confidence": {},
    "snapped": {},
    "source": "none",
    "notes": "",
    "ok": False,
    "reprojection_error_px": None,
}


def autocalibrate(
    frame_path: Path,
    sport: str,
    variant: str | None,
    backend: str = "auto",
    fake_dir: Path | None = None,
    fake_delay_s: float = 0.0,
) -> dict:
    """D-23: propose the landmark clicks from `media/calib.jpg`. Never raises.

    A failure is a proposal with `ok: False` and a note — the uploader falls back to
    asking the user to click, which is the path that was there before.
    """
    if backend == "fake":
        time.sleep(fake_delay_s)
        court = _pipeline_keys_court(fake_dir)
        marks = {k: [float(v[0]), float(v[1])] for k, v in (court.get("landmarks_px") or {}).items()}
        return {
            **EMPTY_PROPOSAL,
            "landmarks_px": marks,
            "confidence": dict.fromkeys(marks, 0.9),
            "source": "fake",
            "ok": bool(marks),
            "reprojection_error_px": 0.02 if marks else None,
        }
    try:
        from courtcam.autocalib import autocalibrate as propose  # type: ignore
        from courtcam.autocalib import read_frame  # type: ignore
        from courtcam.profiles import load_profile  # type: ignore

        frame = read_frame(Path(frame_path))
        return propose(frame, load_profile(sport), variant, backend=backend).as_dict()
    except Exception as exc:  # noqa: BLE001 - autocalibration is always optional
        log.warning("autocalibration unavailable (%s)", exc)
        return {**EMPTY_PROPOSAL, "notes": f"autocalibration unavailable: {exc}"}


def _pipeline_keys_court(fake_dir: Path | None) -> dict:
    fake_dir = Path(fake_dir) if fake_dir else Path(__file__).parent.parent / "fixtures/fake_game"
    try:
        return json.loads((fake_dir / "game.json").read_text()).get("court") or {}
    except (OSError, ValueError):
        return {}


# --------------------------------------------------------------------------- run


def run(
    input_path: Path,
    out_dir: Path,
    game: dict,
    progress: Progress,
    pipeline: str = "courtcam",
    fake_dir: Path | None = None,
    detector: str = "yolo",
    fake_delay_s: float = 0.0,
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
    return _run_fake(input_path, out_dir, fake_dir, progress, fake_delay_s)


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


def _run_fake(
    input_path: Path,
    out_dir: Path,
    fake_dir: Path | None,
    progress: Progress,
    delay_s: float = 0.0,
) -> dict:
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

    # game.json stays API-owned: the fixture's copy would reset id/title/status mid-run
    shutil.copytree(
        fake_dir, out_dir, dirs_exist_ok=True, ignore=shutil.ignore_patterns("game.json")
    )
    # Reported in order so the merged read path (D-9) never shows a later stage done
    # before an earlier one. REPLAY_FAKE_PIPELINE_DELAY_S widens each `running` window.
    for stage in ("detect", "track", "render", "label"):
        progress(stage, 0.5)
        if delay_s > 0:
            time.sleep(delay_s)
        progress(stage, 1.0)

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


def grab_frame(src: Path, dst: Path, at_s: float = 1.0) -> bool:
    """One JPEG out of `src`. Falls back to the first frame when the clip is shorter
    than `at_s`. Used for the thumbnail and for the calibration frame (D-14)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    for seek in (at_s, 0.0):
        cmd = [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-ss",
            str(seek),
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
            log.warning("ffmpeg frame grab at %ss failed (%s)", seek, exc)
            continue
        if dst.is_file() and dst.stat().st_size:
            return True
    return False


def _thumbnail(src: Path, dst: Path) -> None:
    grab_frame(src, dst, 1.0)


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
