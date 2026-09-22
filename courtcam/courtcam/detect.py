"""Stage 3 — person detection (plan §4.4 step 3).

Ultralytics runs detection and ByteTrack association in one pass (D-5), so the
detector already emits track ids; `track.py` turns those per-frame rows into
tracklets. A `Detector` is just a callable, which is how the synthetic
ground-truth detector stands in for YOLO in CI.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from tqdm import tqdm

from .profiles import DetectionCfg

DETS_SCHEMA = "courtcam.dets.v1"


@dataclass(frozen=True, slots=True)
class Detection:
    track_id: int
    box: tuple[float, float, float, float]  # x, y, w, h in pixels
    conf: float


@dataclass(frozen=True, slots=True)
class FrameDets:
    index: int  # frame index in the mezzanine (0-based)
    t: float  # seconds from video start
    dets: list[Detection]


class Detector(Protocol):
    """Yield one `FrameDets` per *sampled* frame, in increasing time order."""

    def __call__(
        self, video: Path, *, stride: int, max_frames: int | None = None
    ) -> Iterator[FrameDets]: ...


class YoloDetector:
    """Ultralytics YOLO + built-in ByteTrack, CPU (D-5)."""

    def __init__(self, cfg: DetectionCfg, fps: float = 30.0, tracker: str = "bytetrack.yaml"):
        self.cfg = cfg
        self.fps = fps
        self.tracker = tracker

    def __call__(
        self, video: Path, *, stride: int, max_frames: int | None = None
    ) -> Iterator[FrameDets]:
        from ultralytics import YOLO  # slow import; keep it off the CLI's hot path

        model = YOLO(self.cfg.model)
        names = {v: k for k, v in model.names.items()}
        classes = [names[c] for c in self.cfg.classes if c in names] or None
        stream = model.track(
            source=str(video),
            stream=True,
            persist=True,
            tracker=self.tracker,
            classes=classes,
            imgsz=self.cfg.imgsz,
            conf=self.cfg.conf,
            vid_stride=stride,
            verbose=False,
        )
        next_id = -1
        for i, result in enumerate(stream):
            index = i * stride
            if max_frames is not None and index >= max_frames:
                break
            dets: list[Detection] = []
            boxes = result.boxes
            if boxes is not None and len(boxes):
                xywh = boxes.xywh.cpu().numpy()
                confs = boxes.conf.cpu().numpy()
                ids = boxes.id.cpu().numpy() if boxes.id is not None else None
                for j in range(len(xywh)):
                    cx, cy, w, h = (float(v) for v in xywh[j])
                    if ids is None:
                        # ByteTrack drops low-confidence boxes before assigning an id;
                        # give them a throwaway negative id so nothing merges onto them.
                        tid = next_id
                        next_id -= 1
                    else:
                        tid = int(ids[j])
                    dets.append(Detection(tid, (cx - w / 2, cy - h / 2, w, h), float(confs[j])))
            yield FrameDets(index, index / self.fps, dets)


class SyntheticDetector:
    """Replays boxes from a synthetic clip's `ground_truth.json` (plan §7.4).

    Lets the whole pipeline run in CI with no model weights.
    """

    def __init__(self, ground_truth: Path):
        self.gt = json.loads(Path(ground_truth).read_text(encoding="utf-8"))

    def __call__(
        self, video: Path, *, stride: int, max_frames: int | None = None
    ) -> Iterator[FrameDets]:
        fps = float(self.gt.get("fps", 30.0))
        for frame in self.gt["frames"]:
            index = int(frame["f"])
            if index % stride:
                continue
            if max_frames is not None and index >= max_frames:
                break
            yield FrameDets(
                index,
                index / fps,
                [
                    Detection(
                        int(d["id"]), tuple(float(v) for v in d["bb"]), float(d.get("c", 1.0))
                    )
                    for d in frame["d"]
                ],
            )


def run_detect(
    video: Path,
    out_path: Path,
    detector: Detector,
    *,
    fps: float,
    width: int,
    height: int,
    stride: int,
    max_frames: int | None = None,
    total_frames: int | None = None,
    show_progress: bool = True,
    on_progress: Any = None,
) -> Path:
    """Run `detector` over `video` and write `out_path` (`courtcam.dets.v1`).

    Skipped entirely if `out_path` already exists — detection is the expensive stage.
    """
    out_path = Path(out_path)
    if out_path.exists():
        return out_path
    limit = max_frames if max_frames is not None else total_frames
    total = (limit + stride - 1) // stride if limit else None
    frames: list[dict[str, Any]] = []
    bar = tqdm(total=total, unit="frame", desc="detect", disable=not show_progress)
    with bar:
        for fd in detector(video, stride=stride, max_frames=max_frames):
            frames.append(
                {
                    "f": fd.index,
                    "t": round(fd.t, 4),
                    "d": [
                        [d.track_id, *(round(v, 2) for v in d.box), round(d.conf, 4)]
                        for d in fd.dets
                    ],
                }
            )
            bar.update(1)
            if on_progress and total:
                on_progress(min(0.99, len(frames) / total))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(
            {
                "schema": DETS_SCHEMA,
                "fps": fps,
                "stride": stride,
                "width": width,
                "height": height,
                "frames": frames,
            }
        ),
        encoding="utf-8",
    )
    return out_path


def make_detector(
    kind: str, cfg: DetectionCfg, *, fps: float = 30.0, ground_truth: Path | None = None
) -> Detector:
    if kind == "synthetic":
        if ground_truth is None:
            raise ValueError("--detector synthetic needs a ground_truth.json (--ground-truth)")
        return SyntheticDetector(ground_truth)
    if kind == "yolo":
        return YoloDetector(cfg, fps=fps)
    raise ValueError(f"unknown detector {kind!r} (expected 'yolo' or 'synthetic')")
