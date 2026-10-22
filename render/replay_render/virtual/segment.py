"""Player masks for one highlight: SAM 2.1 video, box prompts from the tracks (M8).

The play window is cut into chunks of `CHUNK` frames; each chunk is a fresh SAM 2 video
session prompted with the tracked box of every player, each on the first frame of the
chunk where they have a box (a player whose track starts mid-chunk is not lost until the
next chunk), then propagated through every `STRIDE`-th frame of the chunk. Re-prompting
per chunk bounds drift and
identity leaks (docs/models.md: masks drift through clusters) and keeps every GPU call
short. Each mask is then clipped to its player's grown track box, so a mask that
leaks onto a neighbour cannot carry them along.

Output `segments/{play_id}.npz` (+ `.json` index): per player a fixed-size crop window
that follows the track box, `<pid>_xy` (F, 2) crop origins in source pixels and
`<pid>_mask` (F, h, w) bool (packed). A player absent from a frame has an all-false mask.

Runs in-process where torch + transformers 5.x are importable (the shared venv on the
box), bf16 with cuDNN/MIOpen disabled (D-39). `fake=True` writes elliptical masks from
the boxes instead (CPU tests, no model).
"""

from __future__ import annotations

import itertools
import json
import time
from pathlib import Path
from typing import Any

import numpy as np

from ..gamedata import load_tracks
from .replays import frame_count, play, probe_video, read_window

MODEL_ID = "facebook/sam2.1-hiera-small"
# re-prompt every 0.8 s at 30 fps: SAM loses players behind others within a chunk, and
# shorter chunks cost no more (the per-frame image encoding dominates). A Nottingham play:
# masked player-frames 1828 at 48, 2162 at 24, wall 34 s -> 27 s
CHUNK = 24
# SAM sees every STRIDE-th frame; a frame between reuses the one before, moved with its
# track box (half the GPU time; at 30 fps a player moves a few pixels in 1/30 s)
STRIDE = 2
HOLD = 24  # frames a lost player's last mask is held (moved with their box)
GROW = 0.25  # the clip box around a track box, per side, as a fraction of its size
SEGMENTS_DIR = "segments"


def _boxes(game_dir: Path, h: dict, fps: float, n: int, size: tuple[int, int]):
    """{pid: (n, 4) source-pixel boxes (NaN = absent)} at each output frame."""
    tracks = load_tracks(game_dir, *size)
    times = h["t_start"] + np.arange(n) / fps
    boxes = tracks.at(tracks.box, times)
    return {pid: boxes[i] for i, pid in enumerate(tracks.ids) if np.isfinite(boxes[i, :, 0]).any()}


def _windows(boxes: np.ndarray, size: tuple[int, int]) -> tuple[np.ndarray, tuple[int, int]]:
    """Per-frame crop origins (F, 2) and one crop size covering the grown boxes."""
    w = np.nanmax(boxes[:, 2] - boxes[:, 0]) * (1 + 2 * GROW)
    hh = np.nanmax(boxes[:, 3] - boxes[:, 1]) * (1 + 2 * GROW)
    cw, ch = int(min(size[0], np.ceil(w))), int(min(size[1], np.ceil(hh)))
    cx = (boxes[:, 0] + boxes[:, 2]) / 2
    cy = (boxes[:, 1] + boxes[:, 3]) / 2
    ok = np.isfinite(cx)
    idx = np.arange(len(cx))
    cx = np.interp(idx, idx[ok], cx[ok])
    cy = np.interp(idx, idx[ok], cy[ok])
    x0 = np.clip(np.round(cx - cw / 2), 0, size[0] - cw).astype(int)
    y0 = np.clip(np.round(cy - ch / 2), 0, size[1] - ch).astype(int)
    return np.stack([x0, y0], axis=1), (cw, ch)


def _centre(box: np.ndarray) -> np.ndarray:
    return np.array([(box[0] + box[2]) / 2, (box[1] + box[3]) / 2])


def _clip_box(box: np.ndarray, size: tuple[int, int]) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = box
    gx, gy = GROW * (x1 - x0), GROW * (y1 - y0)
    return (
        max(0, int(x0 - gx)),
        max(0, int(y0 - gy)),
        min(size[0], int(np.ceil(x1 + gx))),
        min(size[1], int(np.ceil(y1 + gy))),
    )


def _ellipse(box: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    import cv2

    m = np.zeros((size[1], size[0]), np.uint8)
    x0, y0, x1, y1 = box
    cv2.ellipse(m, (int((x0 + x1) / 2), int((y0 + y1) / 2)),
                (max(1, int((x1 - x0) / 2)), max(1, int((y1 - y0) / 2))), 0, 0, 360, 1, -1)  # fmt: skip
    return m.astype(bool)


class _Sam:
    def __init__(self, model_id: str = MODEL_ID) -> None:
        import torch
        from transformers import Sam2VideoModel, Sam2VideoProcessor

        torch.backends.cudnn.enabled = False  # D-39 (MIOpen on gfx1201)
        self.torch = torch
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.dtype = torch.bfloat16 if self.device == "cuda" else torch.float32
        try:  # the cached snapshot: the Hub's online checks stalled ~80 s per load on the box
            self.model = Sam2VideoModel.from_pretrained(
                model_id, dtype=self.dtype, local_files_only=True
            )
            self.proc = Sam2VideoProcessor.from_pretrained(model_id, local_files_only=True)
        except OSError:  # not downloaded yet
            self.model = Sam2VideoModel.from_pretrained(model_id, dtype=self.dtype)
            self.proc = Sam2VideoProcessor.from_pretrained(model_id)
        self.model = self.model.to(self.device)

    def chunk(self, frames_rgb: list[np.ndarray], prompts: dict[int, tuple[int, list[float]]]):
        """Yields (frame index in chunk, {obj_id: (H, W) bool}); each object is prompted
        with its box on its own first frame (`prompts[obj] = (frame, box)`). An object's
        mask before its prompt frame is meaningless; the caller drops it."""
        from PIL import Image

        torch = self.torch
        with torch.inference_mode():
            sess = self.proc.init_video_session(
                video=[Image.fromarray(f) for f in frames_rgb],
                inference_device=self.device,
                dtype=self.dtype,
            )
            for fi in sorted({fi for fi, _ in prompts.values()}):
                ids = [k for k, (f, _) in prompts.items() if f == fi]
                self.proc.add_inputs_to_inference_session(
                    inference_session=sess,
                    frame_idx=fi,
                    obj_ids=ids,
                    input_boxes=[[prompts[i][1] for i in ids]],
                )
                self.model(inference_session=sess, frame_idx=fi)
            h, w = sess.video_height, sess.video_width
            for o in self.model.propagate_in_video_iterator(sess):
                masks = self.proc.post_process_masks(
                    [o.pred_masks], original_sizes=[[h, w]], binarize=True
                )[0]
                arr = masks.cpu().numpy().reshape(len(sess.obj_ids), h, w)
                yield o.frame_idx, {oid: arr[k] for k, oid in enumerate(sess.obj_ids)}


def segment_play(
    game_dir: Path,
    video: Path,
    play_id: str,
    *,
    fake: bool = False,
    model_id: str = MODEL_ID,
    progress=None,
) -> dict[str, Any]:
    gd = Path(game_dir)
    h = play(gd, play_id)
    info = probe_video(video)
    size, fps = (info["width"], info["height"]), info["fps"]
    n = frame_count(h, fps)
    boxes = _boxes(gd, h, fps, n, size)
    pids = sorted(boxes)
    wins = {p: _windows(boxes[p], size) for p in pids}
    crops = {p: np.zeros((n, wins[p][1][1], wins[p][1][0]), bool) for p in pids}
    sam = None if fake else _Sam(model_id)
    started = time.time()

    def store(f: int, p: str, m: np.ndarray, src: int) -> None:
        """Player `p`'s crop at frame `f` from the full-frame mask `m` of frame `src`
        (the same frame, or the SAM frame before it: moved along with the track box)."""
        x0, y0, x1, y1 = _clip_box(boxes[p][src], size)
        (ox, oy), (cw, ch) = wins[p][0][f], wins[p][1]
        dx, dy = np.round(_centre(boxes[p][f]) - _centre(boxes[p][src])).astype(int)
        sx, sy = ox - dx, oy - dy  # frame f's window, back in frame src's pixels
        ax0, ay0, ax1, ay1 = max(sx, x0), max(sy, y0), min(sx + cw, x1), min(sy + ch, y1)
        if ax1 > ax0 and ay1 > ay0:
            crops[p][f][ay0 - sy : ay1 - sy, ax0 - sx : ax1 - sx] = m[ay0:ay1, ax0:ax1]

    frames = read_window(video, h["t_start"], n)
    for c0 in range(0, n, CHUNK):
        chunk = [f for _, f in itertools.islice(frames, CHUNK)]
        if not chunk:
            break
        # each player's first SAM frame with a box in this chunk: a player who walks in
        # (or whose track starts) mid-chunk is prompted there, not skipped to the next chunk
        sam_f = range(c0, c0 + len(chunk), STRIDE)
        first = {}
        for p in pids:
            j0 = next((j for j, f in enumerate(sam_f) if np.isfinite(boxes[p][f, 0])), None)
            if j0 is not None:
                first[p] = j0
        if sam is None:
            for j in range(len(chunk)):
                for p in pids:
                    if np.isfinite(boxes[p][c0 + j, 0]):
                        store(c0 + j, p, _ellipse(boxes[p][c0 + j], size), c0 + j)
        elif first:
            rgb = [np.ascontiguousarray(f[:, :, ::-1]) for f in chunk[::STRIDE]]
            ids = {k + 1: p for k, p in enumerate(first)}
            prompts = {k: (first[p], boxes[p][sam_f[first[p]]].tolist()) for k, p in ids.items()}
            for j, masks in sam.chunk(rgb, prompts):
                src = c0 + j * STRIDE
                for f in range(src, min(src + STRIDE, c0 + len(chunk))):
                    for k, p in ids.items():
                        if (
                            j >= first[p]
                            and np.isfinite(boxes[p][f, 0])
                            and np.isfinite(boxes[p][src, 0])
                        ):
                            store(f, p, masks[k], src)
        if progress:
            progress(min(1.0, (c0 + len(chunk)) / max(1, n)))
    out_dir = gd / SEGMENTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    arrays: dict[str, np.ndarray] = {}
    index = {}
    for p in pids:
        cov = crops[p].reshape(n, -1).any(axis=1)
        sam_cov = int(cov.sum())
        # SAM drops a player it loses behind another (an empty mask) until the next
        # chunk's prompt; hold their last mask for up to HOLD frames instead. The crop
        # window follows the track box, so a copied crop moves with the player.
        last = -(HOLD + 1)
        for f in range(n):
            if cov[f]:
                last = f
            elif np.isfinite(boxes[p][f, 0]) and f - last <= HOLD:
                crops[p][f] = crops[p][last]
        cov = crops[p].reshape(n, -1).any(axis=1)
        arrays[f"{p}_xy"] = wins[p][0].astype(np.int32)
        arrays[f"{p}_mask"] = np.packbits(crops[p], axis=-1)
        index[p] = {"crop_wh": list(wins[p][1]), "frames_with_mask": int(cov.sum()),
                    "frames_segmented": sam_cov}  # fmt: skip
    np.savez_compressed(out_dir / f"{play_id}.npz", **arrays)
    meta = {
        "schema": "replay.segments.v1",
        "play_id": play_id,
        "model": "ellipse-from-box (fake)"
        if fake
        else f"{model_id} bf16 (transformers Sam2VideoModel)",
        "t_start": h["t_start"],
        "fps": fps,
        "frames": n,
        "chunk": CHUNK,
        "stride": 1 if fake else STRIDE,
        "players": index,
        "wall_s": round(time.time() - started, 2),
    }
    (out_dir / f"{play_id}.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    return meta


class Masks:
    """Read side of `segments/{play_id}.npz`: full-res alpha crops per player/frame."""

    def __init__(self, game_dir: Path, play_id: str) -> None:
        base = Path(game_dir) / SEGMENTS_DIR / play_id
        self.meta = json.loads(base.with_suffix(".json").read_text(encoding="utf-8"))
        self._z = np.load(base.with_suffix(".npz"))
        self._cache: dict[str, np.ndarray] = {}

    @property
    def players(self) -> list[str]:
        return list(self.meta["players"])

    def get(self, pid: str, f: int) -> tuple[tuple[int, int], np.ndarray] | None:
        """((x0, y0), bool mask crop) of player `pid` at frame `f`, or None if empty."""
        if pid not in self.meta["players"] or f >= self.meta["frames"]:
            return None
        cw = self.meta["players"][pid]["crop_wh"][0]
        m = np.unpackbits(self._arr(f"{pid}_mask")[f], axis=-1, count=cw).astype(bool)
        if not m.any():
            return None
        x0, y0 = self._arr(f"{pid}_xy")[f]
        return (int(x0), int(y0)), m

    def _arr(self, key: str) -> np.ndarray:
        """An npz member is decompressed on every access: keep each one (packed bits,
        a few MB per player per play) after the first."""
        if key not in self._cache:
            self._cache[key] = self._z[key]
        return self._cache[key]


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="SAM 2.1 player masks for one highlight")
    ap.add_argument("game_dir", type=Path)
    ap.add_argument("play_id")
    ap.add_argument("--video", type=Path, default=None)
    ap.add_argument("--fake", action="store_true")
    a = ap.parse_args()
    video = a.video or a.game_dir / "media" / "wide.mp4"
    print(json.dumps(segment_play(a.game_dir, video, a.play_id, fake=a.fake), indent=1))


if __name__ == "__main__":
    main()
