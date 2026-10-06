"""Tier A: virtual cameras on the real video, over one highlight window (M8).

`wide` is the source frame, `follow_<pid>` applies courtcam's follow-cam crop path
(crops/<pid>.json), `tight_<pid>` an isolation shot of the same player (a 16:9 window
2.4 box-heights tall, operator-smoothed by `replay_render.camera.smooth`). Every angle
covers exactly the highlight window at the source frame rate, so the TV can cut between
them (and the Tier B angles) without losing its place.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from courtcam.render import open_encoder

from ..camera import ASPECT, TIGHT_FEEL, smooth
from ..gamedata import load_tracks
from .replays import frame_count, play, probe_video, read_window

OUT_W = 1280
TIGHT_BOX_HEIGHTS = 2.4


def _even(v: float) -> int:
    return max(2, round(v / 2) * 2)


def _windows(game_dir: Path, h: dict, kind: str, pid: str, size, fps: float, n: int) -> np.ndarray:
    """(n, 3) [cx, cy, w] source-pixel 16:9 windows."""
    fw, fh = size
    times = h["t_start"] + np.arange(n) / fps
    if kind == "follow":
        doc = json.loads((Path(game_dir) / "crops" / f"{pid}.json").read_text(encoding="utf-8"))
        rects = np.asarray(doc["rects"], dtype=np.float64)
        idx = np.clip(
            np.round((times - float(doc.get("t0", 0.0))) * float(doc.get("rate_hz", 30))),
            0,
            len(rects) - 1,
        )
        r = rects[idx.astype(int)]
        return np.column_stack(
            [(r[:, 0] + r[:, 2] / 2) * fw, (r[:, 1] + r[:, 3] / 2) * fh, r[:, 2] * fw]
        )
    tracks = load_tracks(game_dir, fw, fh)
    i = tracks.index(pid)
    if i is None:
        raise KeyError(f"player {pid} is not tracked")
    b = tracks.at(tracks.box[i : i + 1], times)[0]
    ok = np.isfinite(b[:, 0])
    if not ok.any():
        raise ValueError(f"player {pid} is absent from the window")
    k = np.arange(n)
    b = np.column_stack([np.interp(k, k[ok], b[ok, d]) for d in range(4)])
    raw = np.column_stack([(b[:, 0] + b[:, 2]) / 2, (b[:, 1] + b[:, 3]) / 2,
                           (b[:, 3] - b[:, 1]) * TIGHT_BOX_HEIGHTS * ASPECT])  # fmt: skip
    return smooth(raw, TIGHT_FEEL, fps, fw, fh, min_w=min(fw, 320.0))


def render_angle(
    game_dir: Path,
    video: Path,
    play_id: str,
    stem: str,
    out_path: Path,
    *,
    out_w: int = OUT_W,
    progress=None,
) -> dict[str, Any]:
    started = time.time()
    h = play(game_dir, play_id)
    info = probe_video(video)
    size, fps = (info["width"], info["height"]), info["fps"]
    n = frame_count(h, fps)
    kind, _, pid = stem.partition("_")
    if kind == "wide":
        out = (out_w, _even(out_w * size[1] / size[0]))
        win = None
    else:
        out = (out_w, _even(out_w / ASPECT))
        win = _windows(game_dir, h, kind, pid, size, fps, n)
    proc = open_encoder(Path(out_path), out, fps)
    assert proc.stdin is not None
    try:
        for f, (_, frame) in enumerate(read_window(video, h["t_start"], n)):
            if win is not None:
                cx, cy, w = win[f]
                hh = w / ASPECT
                x0 = int(np.clip(round(cx - w / 2), 0, size[0] - 2))
                y0 = int(np.clip(round(cy - hh / 2), 0, size[1] - 2))
                frame = frame[y0 : min(size[1], y0 + round(hh)), x0 : min(size[0], x0 + round(w))]
            proc.stdin.write(
                np.ascontiguousarray(cv2.resize(frame, out, interpolation=cv2.INTER_AREA)).tobytes()
            )
            if progress:
                progress((f + 1) / n)
    finally:
        proc.stdin.close()
        if proc.wait() != 0:
            raise RuntimeError(f"ffmpeg failed writing {out_path}")
    return {"angle": stem, "frames": n, "wall_s": round(time.time() - started, 2)}
