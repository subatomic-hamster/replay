"""Court plate (M8): the empty court, from a fixed camera's own footage.

Players move; the floor does not. The per-pixel temporal median of frames spread over
the clip is the court with the players gone (`median_plate`), better still when each
frame's player boxes are masked out first so a player standing still for a while does
not survive as a ghost. `topdown` unprojects that plate onto the court plane through the
calibration (homography + D-25 lens) into a metric texture — `px_per_m` pixels per
metre, north-up in court coordinates — which the Tier B renderer lays down as the
floor. `backdrop` does the same for a vertical plane (the wall behind the far end), so
a virtual camera that tilts up sees the hall rather than black.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from . import distortion

PLATE_SCHEMA = "replay.plate.v1"
Box = Sequence[float]  # x0, y0, x1, y1 in source pixels


def sample_times(
    duration_s: float, n: int, t0: float = 0.0, t1: float | None = None
) -> list[float]:
    t1 = duration_s if t1 is None else min(t1, duration_s)
    step = (t1 - t0) / n
    return [t0 + step * (i + 0.5) for i in range(n)]


def read_frames(video: Path, times: Sequence[float]) -> list[np.ndarray]:
    """BGR frames at `times` (seconds), by seeking; missing frames are skipped."""
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise FileNotFoundError(f"cannot open {video}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    out = []
    for t in times:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t * fps)))
        ok, frame = cap.read()
        if ok:
            out.append(frame)
    cap.release()
    return out


def median_plate(
    frames: Sequence[np.ndarray],
    boxes: Sequence[Sequence[Box]] | None = None,
    *,
    pad: float = 0.15,
) -> tuple[np.ndarray, np.ndarray]:
    """(plate BGR uint8, coverage) — per-pixel median over `frames`.

    With `boxes` (per frame, source-pixel boxes of every tracked person, grown by `pad`
    of their size) those pixels are left out of that frame's vote; `coverage` is the
    fraction of frames that voted per pixel. Where nothing voted (someone stood there in
    every sample) the unmasked median fills in.
    """
    stack = np.stack(frames).astype(np.float32)
    plain = np.median(stack, axis=0)
    if not boxes:
        return plain.astype(np.uint8), np.ones(stack.shape[1:3], np.float32)
    h, w = stack.shape[1:3]
    valid = np.ones(stack.shape[:3], bool)
    for i, frame_boxes in enumerate(boxes):
        for x0, y0, x1, y1 in frame_boxes:
            px, py = pad * (x1 - x0), pad * (y1 - y0)
            a, b = max(0, int(x0 - px)), min(w, int(np.ceil(x1 + px)))
            c, d = max(0, int(y0 - py)), min(h, int(np.ceil(y1 + py)))
            valid[i, c:d, a:b] = False
    stack[~valid] = np.nan
    with np.errstate(all="ignore"):
        masked = np.nanmedian(stack, axis=0)
    coverage = valid.mean(axis=0).astype(np.float32)
    plate = np.where(np.isnan(masked), plain, masked)
    return np.clip(plate, 0, 255).astype(np.uint8), coverage


def _remap(plate: np.ndarray, src_xy: np.ndarray, k1: float) -> np.ndarray:
    """Sample `plate` at undistorted pixel coords `src_xy` (H, W, 2); black outside."""
    h, w = plate.shape[:2]
    pts = distortion.distort_points(src_xy.reshape(-1, 2), k1, (w, h)).reshape(src_xy.shape)
    pts = pts.astype(np.float32)
    return cv2.remap(
        plate, pts[..., 0], pts[..., 1], cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT
    )


def topdown(
    plate: np.ndarray,
    h_inv: np.ndarray,
    k1: float,
    bounds_m: tuple[float, float, float, float],
    px_per_m: float = 40.0,
) -> np.ndarray:
    """Metric floor texture over `bounds_m` = (x0, y0, x1, y1) court metres.

    Texture pixel (u, v) is court point (x0 + (u + .5) / px_per_m, y1 - (v + .5) / px_per_m):
    +x to the right, +y up the image (the far end at the top). `h_inv` maps metres to
    undistorted pixels (calib.json `H_inv`); `k1` puts them back through the lens.
    """
    x0, y0, x1, y1 = bounds_m
    tw, th = int(round((x1 - x0) * px_per_m)), int(round((y1 - y0) * px_per_m))
    u, v = np.meshgrid(np.arange(tw) + 0.5, np.arange(th) + 0.5)
    xy = np.stack([x0 + u / px_per_m, y1 - v / px_per_m, np.ones_like(u)], axis=-1)
    hom = xy @ np.asarray(h_inv, dtype=np.float64).T
    behind = hom[..., 2] <= 1e-9
    src = hom[..., :2] / np.where(behind, 1.0, hom[..., 2])[..., None]
    src[behind] = -1e6
    return _remap(plate, src, k1)


def wall_plane(
    bounds_m: tuple[float, float, float, float], forward: np.ndarray
) -> tuple[np.ndarray, np.ndarray, float]:
    """(origin, along, length) of the floor edge facing the camera across the court: the
    side of `bounds_m` the camera's horizontal view direction `forward` points at most."""
    x0, y0, x1, y1 = bounds_m
    if abs(forward[0]) >= abs(forward[1]):  # looking across x: wall is x = const
        x = x1 if forward[0] > 0 else x0
        return np.array([x, y0, 0.0]), np.array([0.0, 1.0, 0.0]), y1 - y0
    y = y1 if forward[1] > 0 else y0
    return np.array([x0, y, 0.0]), np.array([1.0, 0.0, 0.0]), x1 - x0


def backdrop(
    plate: np.ndarray,
    p: np.ndarray,
    k1: float,
    origin: np.ndarray,
    along: np.ndarray,
    length_m: float,
    height_m: float,
    px_per_m: float = 20.0,
) -> np.ndarray:
    """Texture of a vertical wall through camera matrix `p` (3x4, metres -> undistorted
    px). Pixel (u, v) is world point origin + (u + .5) / px_per_m * along +
    (height_m - (v + .5) / px_per_m) * z."""
    tw, th = int(round(length_m * px_per_m)), int(round(height_m * px_per_m))
    u, v = np.meshgrid(np.arange(tw) + 0.5, np.arange(th) + 0.5)
    s, z = u / px_per_m, height_m - v / px_per_m
    world = origin + s[..., None] * along + z[..., None] * np.array([0.0, 0.0, 1.0])
    world = np.concatenate([world, np.ones_like(s)[..., None]], axis=-1)
    hom = world @ np.asarray(p, dtype=np.float64).T
    behind = hom[..., 2] <= 1e-9
    src = hom[..., :2] / np.where(behind, 1.0, hom[..., 2])[..., None]
    src[behind] = -1e6
    return _remap(plate, src, k1)


def track_boxes(
    tracks_dir: Path, times: Sequence[float], size: tuple[int, int]
) -> list[list[tuple[float, float, float, float]]]:
    """Every tracked box (source pixels) at the track sample nearest each of `times`."""
    frames: list[tuple[float, list]] = []
    for f in sorted(Path(tracks_dir).glob("*.json")):
        doc = json.loads(f.read_text(encoding="utf-8"))
        frames.extend((fr["t"], fr["p"]) for fr in doc.get("frames", []))
    if not frames:
        return [[] for _ in times]
    ts = np.asarray([t for t, _ in frames])
    w, h = size
    out = []
    for t in times:
        pts = frames[int(np.abs(ts - t).argmin())][1]
        out.append(
            [(p["bb"][0] * w, p["bb"][1] * h, (p["bb"][0] + p["bb"][2]) * w,
              (p["bb"][1] + p["bb"][3]) * h) for p in pts]
        )  # fmt: skip
    return out


def build_plate(
    video: Path,
    calib: dict[str, Any],
    calibration: dict[str, Any],
    out_dir: Path,
    *,
    tracks_dir: Path | None = None,
    n_frames: int = 41,
    margin_m: float = 3.0,
    px_per_m: float = 40.0,
    wall_h_m: float = 8.0,
    progress: Callable[[float], None] | None = None,
) -> dict[str, Any]:
    """Write `plate.jpg` (source view), `floor.jpg` (top-down) and `backdrop.jpg` plus
    `plate.json` describing their metric frames into `out_dir`."""
    cap = cv2.VideoCapture(str(video))
    duration = (cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0) / (cap.get(cv2.CAP_PROP_FPS) or 30.0)
    cap.release()
    times = sample_times(duration, n_frames)
    frames = read_frames(video, times)
    if not frames:
        raise RuntimeError(f"no frames read from {video}")
    if progress:
        progress(0.4)
    size = (frames[0].shape[1], frames[0].shape[0])
    boxes = track_boxes(tracks_dir, times, size) if tracks_dir else None
    plate, coverage = median_plate(frames, boxes[: len(frames)] if boxes else None)
    if progress:
        progress(0.8)
    k1 = float(calib.get("k1") or 0.0)
    poly = np.asarray(calib["court_polygon_m"], dtype=np.float64)
    (cx0, cy0), (cx1, cy1) = poly.min(axis=0), poly.max(axis=0)
    bounds = (cx0 - margin_m, cy0 - margin_m, cx1 + margin_m, cy1 + margin_m)
    floor = topdown(plate, np.asarray(calib["H_inv"]), k1, bounds, px_per_m)
    from .calibrate import camera_matrix

    forward = np.asarray(calibration["R"], dtype=np.float64)[2]  # optical axis, world
    origin, along, length = wall_plane(bounds, forward)
    wall = backdrop(plate, camera_matrix(calibration), k1, origin, along, length, wall_h_m)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_dir / "plate.jpg"), plate, [cv2.IMWRITE_JPEG_QUALITY, 92])
    cv2.imwrite(str(out_dir / "floor.jpg"), floor, [cv2.IMWRITE_JPEG_QUALITY, 92])
    cv2.imwrite(str(out_dir / "backdrop.jpg"), wall, [cv2.IMWRITE_JPEG_QUALITY, 90])
    meta = {
        "schema": PLATE_SCHEMA,
        "frames": len(frames),
        "times_s": [round(t, 3) for t in times[: len(frames)]],
        "masked_players": boxes is not None,
        "min_coverage": round(float(coverage.min()), 3),
        "image_size": list(size),
        "floor": {"file": "floor.jpg", "bounds_m": list(bounds), "px_per_m": px_per_m},
        "backdrop": {
            "file": "backdrop.jpg",
            "origin_m": origin.tolist(),
            "along": along.tolist(),
            "length_m": float(length),
            "height_m": wall_h_m,
            "px_per_m": 20.0,
        },
    }
    (out_dir / "plate.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    if progress:
        progress(1.0)
    return meta
