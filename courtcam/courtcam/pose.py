"""2D pose per tracked player (plan §4.4 "Detect & pose").

Poses are estimated on a **crop around each track box** of the full-resolution frame,
not on the downscaled whole frame: the crop (box + `pose.margin` per side) is letterboxed
up to `pose.imgsz`, so a 60 px far player is seen ~5x larger than in a 960 px pass over
a 4K frame. Keypoints are mapped back to frame coordinates and normalized like
`tracks/` boxes.

One `poses/{chunk:05d}.json` per tracks chunk, at the tracks' sample times (10 Hz), so the
worker fans the stage out per chunk and a gesture test reads the same clock as the boxes.

Posers: `yolo` (ultralytics YOLO11-pose on the crops), `synthetic` (keypoints from a
synthetic clip's `ground_truth.json`, matched to the track box by IoU — the oracle that
separates trigger-logic errors from pose errors), `none` (empty frames).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from pathlib import Path

import cv2
import numpy as np

from .profiles import PoseCfg
from .schema import PoseFrame, PosePoint, PosesChunk, TracksChunk

Box = tuple[float, float, float, float]  # x, y, w, h in pixels
Found = tuple[np.ndarray, float] | None  # keypoints (17, 3) frame px + score, conf
# (frame index, frame or None, track boxes) -> one result per box
Poser = Callable[[int, np.ndarray | None, list[Box]], list[Found]]


def crop_rect(box: Box, size: tuple[int, int], margin: float) -> tuple[int, int, int, int]:
    """Integer (x0, y0, x1, y1) of `box` grown by `margin`·(w, h) per side, inside the frame."""
    x, y, w, h = box
    W, H = size
    x0 = int(max(0, np.floor(x - margin * w)))
    y0 = int(max(0, np.floor(y - margin * h)))
    x1 = int(min(W, np.ceil(x + w + margin * w)))
    y1 = int(min(H, np.ceil(y + h + margin * h)))
    return x0, y0, x1, y1


def iou(a: Box, b: Box) -> float:
    iw = max(0.0, min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]))
    ih = max(0.0, min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]))
    inter = iw * ih
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union > 0 else 0.0


def pick(track_box: Box, boxes: np.ndarray, kps: np.ndarray, conf, min_iou: float) -> Found:
    """The candidate that is this track's person: best IoU with the track box (all in
    frame pixels), at least `min_iou`. Undetected keypoints get x = y = 0."""
    best, best_iou = None, min_iou
    for i, b in enumerate(boxes):
        v = iou(tuple(b), track_box)
        if v >= best_iou:
            best, best_iou = i, v
    if best is None:
        return None
    kp = np.array(kps[best], dtype=np.float64)
    kp[kp[:, 2] <= 0, :2] = 0.0
    return kp, float(conf[best])


def yolo_poser(cfg: PoseCfg, model: str | None = None) -> Poser:
    """YOLO-pose on one batch of crops per frame (GPU when torch sees one)."""
    from ultralytics import YOLO

    from .detect import gpu_available

    net = YOLO(model or cfg.model)
    device = 0 if gpu_available() else "cpu"

    def run(index: int, img: np.ndarray | None, boxes: list[Box]) -> list[Found]:
        assert img is not None
        H, W = img.shape[:2]
        rects = [crop_rect(b, (W, H), cfg.margin) for b in boxes]
        keep = [k for k, r in enumerate(rects) if r[2] - r[0] >= 4 and r[3] - r[1] >= 4]
        out: list[Found] = [None] * len(boxes)
        if not keep:
            return out
        crops = [img[rects[k][1] : rects[k][3], rects[k][0] : rects[k][2]] for k in keep]
        res = net.predict(crops, imgsz=cfg.imgsz, conf=cfg.conf, device=device, verbose=False)
        for k, r in zip(keep, res, strict=True):
            if r.keypoints is None or len(r.boxes) == 0:
                continue
            ox, oy = rects[k][:2]
            xywh = r.boxes.xywh.cpu().numpy()
            xywh[:, 0] += ox - xywh[:, 2] / 2  # centre -> top-left, crop -> frame
            xywh[:, 1] += oy - xywh[:, 3] / 2
            xy = r.keypoints.xy.cpu().numpy() + [ox, oy]
            kc = r.keypoints.conf
            sc = kc.cpu().numpy() if kc is not None else np.ones(xy.shape[:2])
            kps = np.concatenate([xy, sc[..., None]], axis=2)
            out[k] = pick(boxes[k], xywh, kps, r.boxes.conf.cpu().numpy(), cfg.min_iou)
        return out

    return run


def synthetic_poser(ground_truth: Path, cfg: PoseCfg) -> Poser:
    """Ground-truth COCO keypoints of a synthetic clip (visible 0.9, occluded 0.4)."""
    gt = json.loads(Path(ground_truth).read_text(encoding="utf-8"))
    rows = {int(f["f"]): [r for r in f["d"] if r.get("kp")] for f in gt["frames"]}

    def run(index: int, img: np.ndarray | None, boxes: list[Box]) -> list[Found]:
        here = rows.get(index, [])
        if not here:
            return [None] * len(boxes)
        bb = np.array([r["bb"] for r in here], dtype=np.float64)
        kps = np.array(
            [[[x, y, 0.0 if v == 0 else (0.9 if v == 2 else 0.4)] for x, y, v in r["kp"]]
             for r in here]
        )  # fmt: skip
        conf = np.full(len(here), 0.95)
        return [pick(b, bb, kps, conf, cfg.min_iou) for b in boxes]

    return run


def _frames_at(video: Path, indices: Sequence[int]):
    """Yield (index, BGR frame) for the frame `indices`, decoding forward from the first."""
    want = sorted(set(indices))
    if not want:
        return
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise FileNotFoundError(f"cannot open {video}")
    try:
        cap.set(cv2.CAP_PROP_POS_FRAMES, want[0])
        i = want[0]
        for target in want:
            while i < target:
                if not cap.grab():
                    return
                i += 1
            ok, frame = cap.read()
            if not ok:
                return
            i += 1
            yield target, frame
    finally:
        cap.release()


def estimate_chunk(
    chunk: TracksChunk,
    size: tuple[int, int],
    fps: float,
    poser: Poser,
    *,
    video: Path | None,
    source: str,
) -> PosesChunk:
    """Pose every tracked player at every sample time of one tracks chunk. `video` None
    means the poser needs no pixels (synthetic)."""
    W, H = size
    frames_out = [PoseFrame(t=fr.t) for fr in chunk.frames]
    todo = {int(round(fr.t * fps)): k for k, fr in enumerate(chunk.frames) if fr.p}
    if video is not None:
        frames = _frames_at(video, list(todo))
    else:
        frames = ((i, None) for i in sorted(todo))
    for index, img in frames:
        fr = chunk.frames[todo[index]]
        boxes = [(p.bb[0] * W, p.bb[1] * H, p.bb[2] * W, p.bb[3] * H) for p in fr.p]
        for p, found in zip(fr.p, poser(index, img, boxes), strict=True):
            if found is None:
                continue
            kp, conf = found
            frames_out[todo[index]].p.append(
                PosePoint(
                    id=p.id,
                    kp=[(round(x / W, 5), round(y / H, 5), round(s, 3)) for x, y, s in kp.tolist()],
                    c=round(conf, 3),
                )
            )
    return PosesChunk(t0=chunk.t0, rate_hz=chunk.rate_hz, source=source, frames=frames_out)


def read_poses(poses_dir: Path) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """All chunks -> {player_id: (times (n,), keypoints (n, 17, 3) normalized)}."""
    acc: dict[str, tuple[list, list]] = {}
    for path in sorted(Path(poses_dir).glob("*.json")):
        doc = PosesChunk.model_validate_json(path.read_text(encoding="utf-8"))
        for fr in doc.frames:
            for p in fr.p:
                ts, ks = acc.setdefault(p.id, ([], []))
                ts.append(fr.t)
                ks.append(p.kp)
    return {
        pid: (np.asarray(ts), np.asarray(ks, dtype=np.float64)) for pid, (ts, ks) in acc.items()
    }
