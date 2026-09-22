"""Stage 1 — probe the source and write the mezzanine + still frames (plan §4.4 step 1)."""

from __future__ import annotations

import json
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

from .schema import VideoInfo

MAX_HEIGHT = 2160
TARGET_FPS = 30


def _require(tool: str) -> str:
    path = shutil.which(tool)
    if path is None:
        raise RuntimeError(f"{tool} not found on PATH; courtcam needs ffmpeg + ffprobe")
    return path


@lru_cache(maxsize=1)
def h264_encoder() -> str:
    """First usable H.264 encoder in this ffmpeg build.

    Not every distro ships libx264 (Fedora's stock build does not), so pick at run
    time instead of hard-coding it.
    """
    out = subprocess.run(
        [_require("ffmpeg"), "-hide_banner", "-encoders"], capture_output=True, text=True
    ).stdout
    for name in ("libx264", "libopenh264", "h264_qsv"):
        if f" {name} " in out:
            return name
    raise RuntimeError("no H.264 encoder in this ffmpeg build (need libx264 or libopenh264)")


def h264_args(*, crf: int = 22, bitrate: str = "6M") -> list[str]:
    """Encoder flags for a faststart-friendly H.264 stream."""
    enc = h264_encoder()
    if enc == "libx264":
        return ["-c:v", enc, "-preset", "veryfast", "-crf", str(crf), "-pix_fmt", "yuv420p"]
    # libopenh264 / QSV take a bitrate, not a CRF
    return ["-c:v", enc, "-b:v", bitrate, "-pix_fmt", "yuv420p"]


def probe(path: Path) -> VideoInfo:
    """`ffprobe` the first video stream."""
    out = subprocess.run(
        [
            _require("ffprobe"),
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,avg_frame_rate,duration",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    data = json.loads(out)
    if not data.get("streams"):
        raise ValueError(f"{path}: no video stream")
    s = data["streams"][0]
    num, _, den = s.get("avg_frame_rate", "30/1").partition("/")
    fps = float(num) / float(den or 1) if float(den or 1) else 30.0
    duration = float(s.get("duration") or data.get("format", {}).get("duration") or 0.0)
    return VideoInfo(duration_s=duration, fps=fps, width=int(s["width"]), height=int(s["height"]))


def _still(src: Path, dst: Path, t: float) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            _require("ffmpeg"),
            "-y",
            "-v",
            "error",
            "-ss",
            f"{t:.3f}",
            "-i",
            str(src),
            "-frames:v",
            "1",
            "-q:v",
            "3",
            str(dst),
        ],
        check=True,
        capture_output=True,
    )
    return dst


def ingest(src: Path, media_dir: Path, *, still_t: float = 5.0) -> VideoInfo:
    """Transcode `src` to `media_dir/wide.mp4` (30 fps, H.264, faststart) + stills.

    Returns the info of the *mezzanine*, which is what every later stage reads.
    """
    src, media_dir = Path(src), Path(media_dir)
    info = probe(src)
    media_dir.mkdir(parents=True, exist_ok=True)
    wide = media_dir / "wide.mp4"

    vf = [f"fps={TARGET_FPS}"]
    if info.height > MAX_HEIGHT:
        vf.append(f"scale=-2:{MAX_HEIGHT}")
    # ponytail: software encode always. VAAPI is a ~3x win on long files; add a
    # `-hwaccel`/`h264_vaapi` + hwupload branch behind an env flag when ingest time hurts.
    subprocess.run(
        [
            _require("ffmpeg"),
            "-y",
            "-v",
            "error",
            "-i",
            str(src),
            "-vf",
            ",".join(vf),
            "-fps_mode",
            "cfr",
            "-r",
            str(TARGET_FPS),
            *h264_args(),
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            str(wide),
        ],
        check=True,
        capture_output=True,
    )
    out = probe(wide)
    t = min(still_t, max(0.0, out.duration_s - 0.1))
    _still(wide, media_dir / "thumb.jpg", t)
    _still(wide, media_dir / "calib.jpg", t)
    return out
