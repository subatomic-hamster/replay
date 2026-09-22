"""Stage 9 — rendition-mode rendering and the debug overlay (plan §4.4 step 9).

`client` follow-cam is the default (D-6), so these run lazily and do not need to be
fast. Frames go out over an ffmpeg stdin pipe.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

import cv2
import numpy as np
from tqdm import tqdm

from .ingest import h264_args
from .schema import CropPath

Progress = Callable[[float], None]


def open_encoder(out_path: Path, size: tuple[int, int], fps: float) -> subprocess.Popen:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("ffmpeg not found on PATH")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    return subprocess.Popen(
        [
            ffmpeg,
            "-y",
            "-v",
            "error",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "bgr24",
            "-s",
            f"{size[0]}x{size[1]}",
            "-r",
            f"{fps:g}",
            "-i",
            "-",
            *h264_args(crf=23),
            "-movflags",
            "+faststart",
            str(out_path),
        ],
        stdin=subprocess.PIPE,
    )


def _pipe(
    video: Path,
    out_path: Path,
    size: tuple[int, int],
    draw: Callable[[int, np.ndarray], np.ndarray | None],
    *,
    max_frames: int | None,
    desc: str,
    progress: Progress | None,
    show_progress: bool,
) -> Path:
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise FileNotFoundError(f"cannot open {video}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or None
    if max_frames is not None:
        total = min(total or max_frames, max_frames)
    proc = open_encoder(Path(out_path), size, fps)
    assert proc.stdin is not None
    bar = tqdm(total=total, unit="frame", desc=desc, disable=not show_progress)
    try:
        i = 0
        with bar:
            while max_frames is None or i < max_frames:
                ok, frame = cap.read()
                if not ok:
                    break
                out = draw(i, frame)
                if out is not None:
                    proc.stdin.write(np.ascontiguousarray(out).tobytes())
                i += 1
                bar.update(1)
                if progress and total:
                    progress(min(1.0, i / total))
    finally:
        cap.release()
        if proc.stdin:
            proc.stdin.close()
        if proc.wait() != 0:
            raise RuntimeError(f"ffmpeg failed writing {out_path}")
    return Path(out_path)


def render_crop(
    video: Path,
    crops: CropPath,
    out_path: Path,
    *,
    height: int = 720,
    max_frames: int | None = None,
    progress: Progress | None = None,
    show_progress: bool = True,
) -> Path:
    """Apply a crop path to `video` → a `height`-tall 16:9 MP4 for one player."""
    cap = cv2.VideoCapture(str(video))
    fw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    fh = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    if not fw or not fh:
        raise FileNotFoundError(f"cannot open {video}")
    size = (int(round(height * fw / fh)) // 2 * 2, height)
    rects = crops.rects

    def draw(i: int, frame: np.ndarray) -> np.ndarray:
        r = rects[min(i, len(rects) - 1)] if rects else (0.0, 0.0, 1.0, 1.0)
        x0 = int(round(r[0] * fw))
        y0 = int(round(r[1] * fh))
        x1 = min(fw, x0 + max(2, int(round(r[2] * fw))))
        y1 = min(fh, y0 + max(2, int(round(r[3] * fh))))
        return cv2.resize(frame[y0:y1, x0:x1], size, interpolation=cv2.INTER_AREA)

    return _pipe(
        video,
        out_path,
        size,
        draw,
        max_frames=max_frames,
        desc=f"render {crops.player_id}",
        progress=progress,
        show_progress=show_progress,
    )


def render_overlay(
    video: Path,
    out_path: Path,
    *,
    raw_boxes: dict[int, Sequence[tuple[int, Sequence[float]]]] | None = None,
    player_boxes: dict[int, Sequence[tuple[str, Sequence[float], str]]] | None = None,
    court_polygon_px: np.ndarray | None = None,
    rim_px: Sequence[float] | None = None,
    max_frames: int | None = None,
    progress: Progress | None = None,
    show_progress: bool = True,
) -> Path:
    """Debug MP4: court polygon, dropped raw tracklets in grey, kept players in colour.

    This is how a human checks that boxes land on players and the homography is sane.
    """
    cap = cv2.VideoCapture(str(video))
    fw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    fh = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    if not fw or not fh:
        raise FileNotFoundError(f"cannot open {video}")
    poly = (
        None
        if court_polygon_px is None
        else np.asarray(court_polygon_px, np.int32).reshape(-1, 1, 2)
    )
    raw_boxes = raw_boxes or {}
    player_boxes = player_boxes or {}

    def hex_bgr(h: str) -> tuple[int, int, int]:
        h = h.lstrip("#")
        return (int(h[4:6], 16), int(h[2:4], 16), int(h[0:2], 16))

    def draw(i: int, frame: np.ndarray) -> np.ndarray:
        if poly is not None:
            cv2.polylines(frame, [poly], True, (0, 220, 255), 2)
        if rim_px is not None:
            cv2.circle(frame, (int(rim_px[0]), int(rim_px[1])), 8, (0, 140, 255), 2)
        for tid, box in raw_boxes.get(i, ()):
            x, y, w, h = (int(round(v)) for v in box)
            cv2.rectangle(frame, (x, y), (x + w, y + h), (150, 150, 150), 1)
            cv2.putText(
                frame, f"#{tid}", (x, y - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (150, 150, 150), 1
            )
        for pid, box, color in player_boxes.get(i, ()):
            x, y, w, h = (int(round(v)) for v in box)
            bgr = hex_bgr(color)
            cv2.rectangle(frame, (x, y), (x + w, y + h), bgr, 2)
            cv2.putText(frame, pid, (x, max(14, y - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, bgr, 2)
        return frame

    return _pipe(
        video,
        out_path,
        (fw, fh),
        draw,
        max_frames=max_frames,
        desc="overlay",
        progress=progress,
        show_progress=show_progress,
    )
